"""Opções de pagamento de uma parcela e geração da cobrança no PagBank.

O valor sempre vem da parcela no banco (nunca de quem pediu). Uma cobrança pendente
e ainda válida para o mesmo valor é reaproveitada em vez de criar outra.
"""
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from vendas.models import Parcela
from vendas.services.erros import ErroDeNegocio

from ..models import Cobranca, ConfiguracaoPagamentoOnline
from ..pagbank import cliente, payloads
from ..taxas import total_boleto, total_cartao, total_pix

logger = logging.getLogger(__name__)

Forma = Cobranca.Forma
CAMINHO_NOTIFICACAO = '/api/pagbank/notificacao/'
FOLGA_REUSO = {Forma.PIX: timedelta(minutes=10), Forma.CARTAO: timedelta(minutes=10), Forma.BOLETO: timedelta(days=1)}
EM_CRIACAO = timedelta(seconds=60)  # mais que o timeout da chamada ao PagBank
CAMPO_EXIGIDO = {Forma.PIX: 'pix_copia_cola', Forma.BOLETO: 'boleto_linha_digitavel', Forma.CARTAO: 'link_pagamento'}


@dataclass(frozen=True)
class Opcao:
    forma: str
    rotulo: str
    valor_parcela: Decimal
    taxa: Decimal
    total: Decimal
    max_parcelas_cartao: int | None = None

    def como_dict(self) -> dict:
        dados = asdict(self)
        return {**dados, **{c: str(dados[c]) for c in ('valor_parcela', 'taxa', 'total')}}


def disponivel(configuracao: ConfiguracaoPagamentoOnline | None = None) -> bool:
    configuracao = configuracao or ConfiguracaoPagamentoOnline.obter()
    return configuracao.ativo and cliente.configurado()


def _formas_ativas(configuracao: ConfiguracaoPagamentoOnline) -> list[str]:
    ligadas = {Forma.PIX: configuracao.pix_ativo, Forma.BOLETO: configuracao.boleto_ativo,
               Forma.CARTAO: configuracao.cartao_ativo}
    return [forma for forma, ligada in ligadas.items() if ligada]


def _totais(forma: str, valor: Decimal, configuracao: ConfiguracaoPagamentoOnline) -> tuple[Decimal, Decimal]:
    if forma == Forma.BOLETO:
        return total_boleto(valor, configuracao.taxa_boleto)
    if forma == Forma.CARTAO:
        return total_cartao(valor, configuracao.taxa_cartao_percentual)
    return total_pix(valor)


def opcoes_da_parcela(parcela: Parcela, configuracao: ConfiguracaoPagamentoOnline | None = None) -> list[Opcao]:
    configuracao = configuracao or ConfiguracaoPagamentoOnline.obter()
    valor = parcela.valor_restante
    if parcela.pago or valor <= 0 or not disponivel(configuracao):
        return []
    opcoes = []
    for forma in _formas_ativas(configuracao):
        total, taxa = _totais(forma, valor, configuracao)
        opcoes.append(Opcao(
            forma=forma, rotulo=Forma(forma).label, valor_parcela=valor, taxa=taxa, total=total,
            max_parcelas_cartao=configuracao.cartao_max_parcelas if forma == Forma.CARTAO else None,
        ))
    return opcoes


def url_notificacao() -> str:
    from crm.models import ConfiguracaoCRM

    base = ConfiguracaoCRM.obter().url_publica.strip().rstrip('/')
    if not base:
        raise ErroDeNegocio('Configure o endereço público do sistema no CRM para receber os avisos do PagBank.')
    return f'{base}{CAMINHO_NOTIFICACAO}'


def _pagador(parcela: Parcela, configuracao: ConfiguracaoPagamentoOnline) -> payloads.Pagador:
    cliente_venda = parcela.pagamento.venda.cliente
    email = (cliente_venda.email or '').strip() or configuracao.email_padrao
    if not email:
        raise ErroDeNegocio('Cliente sem e-mail e nenhum e-mail padrão configurado para as cobranças.')
    return payloads.Pagador(
        nome=cliente_venda.nome, cpf=cliente_venda.cpf, email=email, telefone=cliente_venda.telefone,
        endereco=cliente_venda.endereco, bairro=cliente_venda.bairro, cidade=cliente_venda.cidade,
        uf=configuracao.uf_padrao, cep=cliente_venda.cep,
    )


def _descricao(parcela: Parcela) -> str:
    pagamento = parcela.pagamento
    return f'Parcela {parcela.numero_parcela}/{pagamento.parcelas or "?"} - compra {pagamento.venda_id}'


def _expiracao(forma: str, configuracao: ConfiguracaoPagamentoOnline) -> datetime:
    if forma == Forma.BOLETO:
        vencimento = timezone.localdate() + timedelta(days=configuracao.boleto_dias_vencimento)
        return timezone.make_aware(datetime.combine(vencimento, time(23, 59, 59)))
    return timezone.now() + timedelta(hours=configuracao.validade_horas)


def _reaproveitavel(parcela: Parcela, forma: str, valor: Decimal, total: Decimal) -> Cobranca | None:
    limite = timezone.now() + FOLGA_REUSO[forma]
    return (Cobranca.objects
            .filter(parcela=parcela, forma=forma, status=Cobranca.Status.PENDENTE, valor_parcela=valor,
                    valor_total=total, expira_em__gt=limite)
            .exclude(pagbank_id='')
            .order_by('-criado_em').first())


def _em_criacao(parcela: Parcela, forma: str) -> bool:
    """Outra requisição (duplo clique, bot e backoffice juntos) está esperando o PagBank para esta parcela."""
    recente = timezone.now() - EM_CRIACAO
    return Cobranca.objects.filter(parcela=parcela, forma=forma, status=Cobranca.Status.PENDENTE,
                                   pagbank_id='', criado_em__gt=recente).exists()


def _validar(parcela: Parcela, forma: str, configuracao: ConfiguracaoPagamentoOnline) -> None:
    if not configuracao.ativo:
        raise ErroDeNegocio('O pagamento online está desligado.')
    if not cliente.configurado():
        raise ErroDeNegocio('O PagBank não está configurado no servidor.')
    if forma not in _formas_ativas(configuracao):
        raise ErroDeNegocio('Essa forma de pagamento não está disponível.')
    if parcela.pago or parcela.valor_restante <= 0:
        raise ErroDeNegocio('Essa parcela já está paga.')
    pagamento = parcela.pagamento
    if pagamento.quitado or pagamento.desativado or pagamento.devolucao or pagamento.venda.is_deleted:
        raise ErroDeNegocio('Essa compra não aceita pagamento online. Fale com a nossa equipe.')


def _corpo(cobranca: Cobranca, cobrar: payloads.Cobrar, configuracao: ConfiguracaoPagamentoOnline) -> dict:
    if cobranca.forma == Forma.BOLETO:
        instrucao = f'Parcela {cobranca.parcela.numero_parcela} - CredFacil'
        return payloads.pedido_boleto(cobrar, timezone.localdate(cobranca.expira_em), instrucao)
    if cobranca.forma == Forma.CARTAO:
        token = cobranca.parcela.pagamento.token_publico
        retorno = configuracao.link_app(f'pagamento/{token}?cobranca={cobranca.referencia}')
        return payloads.checkout_cartao(cobrar, cobranca.expira_em, configuracao.cartao_max_parcelas, retorno)
    return payloads.pedido_pix(cobrar, cobranca.expira_em)


def _enviar(cobranca: Cobranca, corpo: dict) -> dict:
    if cobranca.forma == Forma.CARTAO:
        resposta = cliente.criar_checkout(corpo, cobranca=cobranca)
        return {'pagbank_id': resposta.get('id', ''), **payloads.ler_checkout(resposta)}
    resposta = cliente.criar_pedido(corpo, cobranca=cobranca)
    leitura = payloads.ler_boleto(resposta) if cobranca.forma == Forma.BOLETO else payloads.ler_pix(resposta)
    return {'pagbank_id': resposta.get('id', ''), **leitura}


def _cancelar(cobranca: Cobranca, detalhes: dict) -> None:
    cobranca.status = Cobranca.Status.CANCELADA
    cobranca.detalhes_pagamento = detalhes
    cobranca.save(update_fields=['status', 'detalhes_pagamento', 'atualizado_em'])


def _reservar(parcela: Parcela, forma: str, origem: str, usuario) -> tuple[Cobranca, payloads.Cobrar, bool]:
    """Trava a parcela, valida e devolve (cobrança, dados para o PagBank, reaproveitada?)."""
    configuracao = ConfiguracaoPagamentoOnline.obter()
    with transaction.atomic():
        parcela = (Parcela.objects.select_for_update()
                   .select_related('pagamento__venda__cliente').get(pk=parcela.pk))
        _validar(parcela, forma, configuracao)
        valor = parcela.valor_restante
        total, taxa = _totais(forma, valor, configuracao)
        existente = _reaproveitavel(parcela, forma, valor, total)
        if existente:
            return existente, None, True
        if _em_criacao(parcela, forma):
            raise ErroDeNegocio('Essa cobrança já está sendo gerada. Aguarde alguns segundos e tente de novo.')
        cobrar = payloads.Cobrar(
            referencia='', descricao=_descricao(parcela), valor=total,
            pagador=_pagador(parcela, configuracao), url_notificacao=url_notificacao(),
        )
        cobranca = Cobranca.objects.create(
            parcela=parcela, forma=forma, origem=origem, valor_parcela=valor, taxa=taxa, valor_total=total,
            expira_em=_expiracao(forma, configuracao), criado_por=usuario,
        )
    return cobranca, replace(cobrar, referencia=str(cobranca.referencia)), False


def gerar_cobranca(parcela: Parcela, forma: str, origem: str, usuario=None) -> Cobranca:
    cobranca, cobrar, reaproveitada = _reservar(parcela, forma, origem, usuario)
    if reaproveitada:
        return cobranca
    try:
        campos = _enviar(cobranca, _corpo(cobranca, cobrar, ConfiguracaoPagamentoOnline.obter()))
    except cliente.ErroPagBank as erro:
        _cancelar(cobranca, {'erro': erro.mensagem, 'detalhes': str(erro.detalhes or '')[:500]})
        raise ErroDeNegocio(cliente.MENSAGEM_PADRAO) from erro
    if not campos.get('pagbank_id') or not campos.get(CAMPO_EXIGIDO[cobranca.forma]):
        logger.error('Resposta do PagBank sem os dados da cobrança %s: %s', cobranca.pk, campos)
        _cancelar(cobranca, {'erro': 'resposta incompleta'})
        raise ErroDeNegocio(cliente.MENSAGEM_PADRAO)
    for campo, valor_campo in campos.items():
        setattr(cobranca, campo, valor_campo)
    cobranca.save(update_fields=[*campos, 'atualizado_em'])
    return cobranca
