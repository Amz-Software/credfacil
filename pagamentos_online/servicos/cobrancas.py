"""Opções de pagamento e geração da cobrança no PagBank (uma parcela, várias ou a quitação).

O valor sempre vem das parcelas no banco (nunca de quem pediu). Uma cobrança pendente e ainda
válida para as mesmas parcelas e o mesmo valor é reaproveitada em vez de criar outra.
"""
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from vendas.models import Pagamento, Parcela
from vendas.services.erros import ErroDeNegocio

from ..models import Cobranca, ConfiguracaoPagamentoOnline, ItemCobranca
from ..pagbank import cliente, payloads
from ..taxas import total_boleto, total_cartao, total_pix
from .planos import Plano, juntar, plano_de_parcelas, plano_de_quitacao, rotulo_do_plano

logger = logging.getLogger(__name__)

Forma = Cobranca.Forma
CAMINHO_NOTIFICACAO = '/api/pagbank/notificacao/'
FOLGA_REUSO = {Forma.PIX: timedelta(minutes=10), Forma.CARTAO: timedelta(minutes=10), Forma.BOLETO: timedelta(days=1)}
EM_CRIACAO = timedelta(seconds=60)  # mais que o timeout da chamada ao PagBank
CAMPO_EXIGIDO = {Forma.PIX: 'pix_copia_cola', Forma.BOLETO: 'boleto_linha_digitavel', Forma.CARTAO: 'link_pagamento'}
MAX_PARCELAS_POR_COBRANCA = 60
MAX_ID = 2**31 - 1


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


def opcoes_para_valor(valor: Decimal, configuracao: ConfiguracaoPagamentoOnline | None = None) -> list[Opcao]:
    """Cada forma ligada com a taxa somada (a taxa fica com o cliente, menos no Pix)."""
    configuracao = configuracao or ConfiguracaoPagamentoOnline.obter()
    if valor <= 0 or not disponivel(configuracao):
        return []
    opcoes = []
    for forma in _formas_ativas(configuracao):
        total, taxa = _totais(forma, valor, configuracao)
        opcoes.append(Opcao(
            forma=forma, rotulo=Forma(forma).label, valor_parcela=valor, taxa=taxa, total=total,
            max_parcelas_cartao=configuracao.cartao_max_parcelas if forma == Forma.CARTAO else None,
        ))
    return opcoes


def opcoes_da_parcela(parcela: Parcela, configuracao: ConfiguracaoPagamentoOnline | None = None) -> list[Opcao]:
    if parcela.pago:
        return []
    return opcoes_para_valor(parcela.valor_restante, configuracao)


def _parcelas_abertas(pagamento: Pagamento) -> list[Parcela]:
    return list(pagamento.parcelas_pagamento.filter(pago=False).select_related('pagamento__venda__cliente'))


def plano_para_exibir(pagamento: Pagamento, parcela_ids: list[int] | None) -> Plano:
    """Plano sem travar nada (para mostrar valores e opções). `parcela_ids` None = quitação."""
    if parcela_ids is None:
        return plano_de_quitacao(pagamento, _parcelas_abertas(pagamento))
    ids = set(parcela_ids)
    if len(ids) > MAX_PARCELAS_POR_COBRANCA:
        raise ErroDeNegocio('Parcelas demais numa cobrança só.')
    parcelas = list(pagamento.parcelas_pagamento.filter(pk__in=ids))
    if len(parcelas) != len(ids):
        raise ErroDeNegocio('Parcela não encontrada nessa compra.')
    return plano_de_parcelas(pagamento, parcelas)


def quitacao_do_pagamento(pagamento: Pagamento) -> Plano | None:
    """Plano da quitação (para mostrar); None quando não há parcela em aberto."""
    try:
        return plano_de_quitacao(pagamento, _parcelas_abertas(pagamento))
    except ErroDeNegocio:
        return None


def url_notificacao() -> str:
    from crm.models import ConfiguracaoCRM

    base = ConfiguracaoCRM.obter().url_publica.strip().rstrip('/')
    if not base:
        raise ErroDeNegocio('Configure o endereço público do sistema no CRM para receber os avisos do PagBank.')
    return f'{base}{CAMINHO_NOTIFICACAO}'


def _pagador(pagamento: Pagamento, configuracao: ConfiguracaoPagamentoOnline) -> payloads.Pagador:
    cliente_venda = pagamento.venda.cliente
    email = (cliente_venda.email or '').strip() or configuracao.email_padrao
    if not email:
        raise ErroDeNegocio('Cliente sem e-mail e nenhum e-mail padrão configurado para as cobranças.')
    return payloads.Pagador(
        nome=cliente_venda.nome, cpf=cliente_venda.cpf, email=email, telefone=cliente_venda.telefone,
        endereco=cliente_venda.endereco, bairro=cliente_venda.bairro, cidade=cliente_venda.cidade,
        uf=configuracao.uf_padrao, cep=cliente_venda.cep,
    )


def _descricao(plano: Plano) -> str:
    pagamento = plano.pagamento
    if plano.tipo == Cobranca.Tipo.QUITACAO:
        return f'Quitacao - compra {pagamento.venda_id}'
    return f'{rotulo_do_plano(plano)}/{pagamento.parcelas or "?"} - compra {pagamento.venda_id}'


def _expiracao(forma: str, configuracao: ConfiguracaoPagamentoOnline) -> datetime:
    if forma == Forma.BOLETO:
        vencimento = timezone.localdate() + timedelta(days=configuracao.boleto_dias_vencimento)
        return timezone.make_aware(datetime.combine(vencimento, time(23, 59, 59)))
    return timezone.now() + timedelta(hours=configuracao.validade_horas)


def _parcelas_da_cobranca(cobranca: Cobranca) -> frozenset[int]:
    return frozenset(item.parcela_id for item in cobranca.itens_da_baixa())


def _reaproveitavel(plano: Plano, forma: str, total: Decimal) -> Cobranca | None:
    limite = timezone.now() + FOLGA_REUSO[forma]
    candidatas = (Cobranca.objects
                  .filter(parcela=plano.primeira, tipo=plano.tipo, forma=forma, status=Cobranca.Status.PENDENTE,
                          valor_parcela=plano.valor, valor_total=total, expira_em__gt=limite)
                  .exclude(pagbank_id='')
                  .order_by('-criado_em'))
    return next((c for c in candidatas if _parcelas_da_cobranca(c) == plano.parcela_ids), None)


def _em_criacao(plano: Plano, forma: str) -> bool:
    """Outra requisição (duplo clique, bot e backoffice juntos) está esperando o PagBank para estas parcelas."""
    recente = timezone.now() - EM_CRIACAO
    return Cobranca.objects.filter(
        itens__parcela__in=plano.parcela_ids, forma=forma, status=Cobranca.Status.PENDENTE,
        pagbank_id='', criado_em__gt=recente,
    ).exists()


def _validar(pagamento: Pagamento, forma: str, configuracao: ConfiguracaoPagamentoOnline) -> None:
    if not configuracao.ativo:
        raise ErroDeNegocio('O pagamento online está desligado.')
    if not cliente.configurado():
        raise ErroDeNegocio('O PagBank não está configurado no servidor.')
    if forma not in _formas_ativas(configuracao):
        raise ErroDeNegocio('Essa forma de pagamento não está disponível.')
    if pagamento.quitado or pagamento.desativado or pagamento.devolucao or pagamento.venda.is_deleted:
        raise ErroDeNegocio('Essa compra não aceita pagamento online. Fale com a nossa equipe.')


def _corpo(cobranca: Cobranca, cobrar: payloads.Cobrar, plano: Plano, configuracao) -> dict:
    if cobranca.forma == Forma.BOLETO:
        instrucao = f'{rotulo_do_plano(plano)} - CredFacil'
        return payloads.pedido_boleto(cobrar, timezone.localdate(cobranca.expira_em), instrucao)
    if cobranca.forma == Forma.CARTAO:
        token = plano.pagamento.token_publico
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


def _travar(pagamento_id: int, parcela_ids: list[int] | None) -> tuple[Pagamento, list[Parcela]]:
    """Trava as parcelas (todas as em aberto, quando `parcela_ids` é None) em ordem de pk."""
    parcelas = Parcela.objects.select_for_update().filter(pagamento_id=pagamento_id)
    if parcela_ids is None:
        parcelas = parcelas.filter(pago=False)
    else:
        if len(set(parcela_ids)) > MAX_PARCELAS_POR_COBRANCA:
            raise ErroDeNegocio('Parcelas demais numa cobrança só.')
        parcelas = parcelas.filter(pk__in=set(parcela_ids))
    travadas = list(parcelas.order_by('pk'))
    if parcela_ids is not None and len(travadas) != len(set(parcela_ids)):
        raise ErroDeNegocio('Parcela não encontrada nessa compra.')
    pagamento = Pagamento.objects.select_related('venda__cliente').get(pk=pagamento_id)
    return pagamento, travadas


def _exigir_cobravel(plano: Plano) -> None:
    """Sem valor a cobrar ou com parcela já informada como paga (aguardando a equipe): não gera, evita pagar duas vezes."""
    if plano.valor <= 0:
        raise ErroDeNegocio('Não há valor a cobrar. Fale com a nossa equipe.')
    informadas = [item.parcela.numero_parcela for item in plano.itens if item.parcela.pagamento_efetuado]
    if informadas:
        raise ErroDeNegocio(f'O pagamento da parcela {juntar(informadas)} já foi informado e aguarda a conferência '
                            'da nossa equipe. Fale com a gente antes de pagar de novo.')


def _montar_plano(pagamento: Pagamento, parcelas: list[Parcela], quitacao: bool) -> Plano:
    return plano_de_quitacao(pagamento, parcelas) if quitacao else plano_de_parcelas(pagamento, parcelas)


def _reservar(pagamento_id: int, parcela_ids: list[int] | None, forma: str, origem: str,
              usuario) -> tuple[Cobranca, payloads.Cobrar | None, Plano | None]:
    """Trava as parcelas, valida e devolve (cobrança, dados para o PagBank, plano). Reaproveitada: (c, None, None)."""
    configuracao = ConfiguracaoPagamentoOnline.obter()
    with transaction.atomic():
        pagamento, parcelas = _travar(pagamento_id, parcela_ids)
        _validar(pagamento, forma, configuracao)
        plano = _montar_plano(pagamento, parcelas, quitacao=parcela_ids is None)
        _exigir_cobravel(plano)
        total, taxa = _totais(forma, plano.valor, configuracao)
        existente = _reaproveitavel(plano, forma, total)
        if existente:
            return existente, None, None
        if _em_criacao(plano, forma):
            raise ErroDeNegocio('Essa cobrança já está sendo gerada. Aguarde alguns segundos e tente de novo.')
        cobrar = payloads.Cobrar(
            referencia='', descricao=_descricao(plano), valor=total,
            pagador=_pagador(pagamento, configuracao), url_notificacao=url_notificacao(),
        )
        cobranca = Cobranca.objects.create(
            tipo=plano.tipo, parcela=plano.primeira, forma=forma, origem=origem, valor_parcela=plano.valor,
            taxa=taxa, valor_total=total, expira_em=_expiracao(forma, configuracao), criado_por=usuario,
        )
        ItemCobranca.objects.bulk_create([
            ItemCobranca(cobranca=cobranca, parcela=item.parcela, valor=item.valor, desconto=item.desconto)
            for item in plano.itens
        ])
    return cobranca, replace(cobrar, referencia=str(cobranca.referencia)), plano


def _gerar(pagamento_id: int, parcela_ids: list[int] | None, forma: str, origem: str, usuario) -> Cobranca:
    cobranca, cobrar, plano = _reservar(pagamento_id, parcela_ids, forma, origem, usuario)
    if plano is None:
        return cobranca
    try:
        campos = _enviar(cobranca, _corpo(cobranca, cobrar, plano, ConfiguracaoPagamentoOnline.obter()))
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


def gerar_cobranca(parcela: Parcela, forma: str, origem: str, usuario=None) -> Cobranca:
    return _gerar(parcela.pagamento_id, [parcela.pk], forma, origem, usuario)


def gerar_cobranca_de_parcelas(pagamento: Pagamento, parcela_ids: list[int], forma: str, origem: str,
                               usuario=None) -> Cobranca:
    """Uma cobrança só para várias parcelas da mesma compra (sem desconto)."""
    if not parcela_ids:
        raise ErroDeNegocio('Escolha ao menos uma parcela.')
    return _gerar(pagamento.pk, list(parcela_ids), forma, origem, usuario)


def gerar_quitacao(pagamento: Pagamento, forma: str, origem: str, usuario=None) -> Cobranca:
    """Todas as parcelas em aberto com o desconto do plano."""
    return _gerar(pagamento.pk, None, forma, origem, usuario)


def gerar_cobranca_agrupada(pagamento: Pagamento, forma: str, origem: str, parcela_ids: list[int] | None = None,
                            quitacao: bool = False, usuario=None) -> Cobranca:
    """Entrada única do app, do backoffice e do bot: várias parcelas ou a quitação."""
    if quitacao == bool(parcela_ids):
        raise ErroDeNegocio('Informe as parcelas ou a quitação.')
    if quitacao:
        return gerar_quitacao(pagamento, forma, origem, usuario)
    return gerar_cobranca_de_parcelas(pagamento, parcela_ids, forma, origem, usuario)
