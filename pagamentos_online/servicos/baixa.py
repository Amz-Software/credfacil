"""Baixa automática: o PagBank avisa, o sistema confere o pedido na API e dá baixa na parcela.

Nunca confia só no corpo da notificação: o pedido é sempre consultado de novo.
Processar o mesmo pagamento duas vezes não dá baixa em dobro.
"""
import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from vendas.models import ORIGEM_BAIXA_PAGBANK, Pagamento, Parcela

from ..models import Cobranca
from ..pagbank import cliente, payloads
from .planos import juntar

logger = logging.getLogger(__name__)

PREFIXO_PEDIDO = 'ORDE_'
PREFIXO_CHECKOUT = 'CHEC_'
ZERO = Decimal('0')
CAMPOS_PARCELA = ['valor', 'valor_pago', 'pago', 'data_pagamento', 'origem_baixa', 'modificado_em']


def _uuids(textos) -> list[uuid.UUID]:
    validos = []
    for texto in textos:
        try:
            validos.append(uuid.UUID(str(texto)))
        except ValueError:
            continue
    return validos


def localizar(situacao: payloads.SituacaoPedido, checkout_id: str = '') -> Cobranca | None:
    por_referencia = Cobranca.objects.filter(referencia__in=_uuids(situacao.referencias)).first()
    if por_referencia:
        return por_referencia
    if situacao.pedido_id:
        por_pedido = Cobranca.objects.filter(pagbank_id=situacao.pedido_id).first()
        if por_pedido:
            return por_pedido
    if not checkout_id:
        return None
    # O cabeçalho x-product-id não é assinado: só vale se o pedido pago cobre a cobrança do checkout.
    por_checkout = Cobranca.objects.filter(pagbank_id=checkout_id, forma=Cobranca.Forma.CARTAO).first()
    if por_checkout and situacao.valor_pago is not None and situacao.valor_pago >= por_checkout.valor_total:
        return por_checkout
    return None


def _saldo_a_creditar(cobranca: Cobranca, situacao: payloads.SituacaoPedido) -> tuple[Decimal, bool, list[str]]:
    """(quanto entra nas parcelas, pago por inteiro?, divergências). A taxa da forma de pagamento não entra."""
    pago = situacao.valor_pago
    if pago is None or pago >= cobranca.valor_total:
        return cobranca.valor_parcela, True, []
    aviso = f'Pago a menor: R$ {pago} de R$ {cobranca.valor_total}.'
    if cobranca.tipo == Cobranca.Tipo.QUITACAO:
        aviso += ' O desconto da quitação não foi aplicado.'
    return min(cobranca.valor_parcela, pago), False, [aviso]


def _baixar(parcela: Parcela, credito: Decimal, desconto: Decimal, quando) -> None:
    if desconto:  # quitação: o valor da parcela cai pelo desconto, como na confirmação manual
        parcela.valor -= desconto
    parcela.valor_pago = (parcela.valor_pago or ZERO) + credito
    parcela.pago = parcela.valor_restante <= 0
    parcela.data_pagamento = timezone.localdate(quando)
    parcela.origem_baixa = ORIGEM_BAIXA_PAGBANK
    parcela.save(update_fields=CAMPOS_PARCELA)


def _aplicar_nas_parcelas(cobranca: Cobranca, situacao: payloads.SituacaoPedido, quando) -> list[str]:
    """Dá baixa no que foi pago, parcela por parcela, e devolve as divergências (vazio quando está tudo certo)."""
    saldo, inteiro, avisos = _saldo_a_creditar(cobranca, situacao)
    itens = cobranca.itens_da_baixa()
    parcelas = {p.pk: p for p in Parcela.objects.select_for_update()
                .filter(pk__in=[i.parcela_id for i in itens]).order_by('pk')}
    ja_pagas = []
    for item in itens:
        parcela = parcelas[item.parcela_id]
        if parcela.pago:
            ja_pagas.append(parcela.numero_parcela)
            continue
        desconto = item.desconto if inteiro else ZERO
        necessario = max(parcela.valor_restante - desconto, ZERO)
        credito = min(saldo, necessario)
        if credito <= 0:
            continue
        _baixar(parcela, credito, desconto if credito == necessario else ZERO, quando)
        saldo -= credito
    if len(ja_pagas) == len(itens):
        cobranca.pagamento_duplicado = True
        avisos.append('A parcela já estava paga: estorno ou acerto manual.' if len(itens) == 1
                      else 'As parcelas já estavam pagas: estorno ou acerto manual.')
    else:
        if ja_pagas:
            avisos.append(f'Parcela(s) {juntar(ja_pagas)} já estava(m) paga(s).')
        if saldo > 0:
            avisos.append(f'Pago além do saldo das parcelas: excedente de R$ {saldo}.')
    if cobranca.tipo == Cobranca.Tipo.QUITACAO and inteiro:
        _marcar_quitado(cobranca.parcela.pagamento_id)
    return avisos


def _marcar_quitado(pagamento_id: int) -> None:
    if Parcela.objects.filter(pagamento_id=pagamento_id, pago=False).exists():
        return
    pagamento = Pagamento.objects.get(pk=pagamento_id)
    pagamento.quitado = True
    pagamento.save(update_fields=['quitado', 'modificado_em'])  # com update_fields: o signal não recria as parcelas


def _anotar_pedido_extra(cobranca: Cobranca, situacao: payloads.SituacaoPedido) -> None:
    """Outro pedido pago para uma cobrança já paga (ex.: checkout pago duas vezes)."""
    if not situacao.pedido_id or situacao.pedido_id == cobranca.pagbank_pedido_id:
        return
    if situacao.pedido_id in cobranca.acerto_manual:
        return
    logger.warning('Cobrança %s recebeu outro pedido pago (%s).', cobranca.pk, situacao.pedido_id)
    cobranca.acerto_manual = '\n'.join(filter(None, [
        cobranca.acerto_manual, f'Outro pedido pago para esta cobrança: {situacao.pedido_id} (R$ {situacao.valor_pago}).',
    ]))
    cobranca.save(update_fields=['acerto_manual', 'atualizado_em'])


def registrar_pagamento(cobranca: Cobranca, situacao: payloads.SituacaoPedido) -> bool:
    """Marca a cobrança como paga e dá baixa. Devolve True só na primeira vez."""
    with transaction.atomic():
        cobranca = Cobranca.objects.select_for_update().get(pk=cobranca.pk)
        if cobranca.status == Cobranca.Status.PAGA:
            _anotar_pedido_extra(cobranca, situacao)
            return False
        quando = situacao.pago_em or timezone.now()
        cobranca.status = Cobranca.Status.PAGA
        cobranca.paga_em = quando
        cobranca.valor_pago = situacao.valor_pago
        cobranca.pagbank_pedido_id = situacao.pedido_id
        cobranca.detalhes_pagamento = situacao.detalhes
        cobranca.acerto_manual = '\n'.join(_aplicar_nas_parcelas(cobranca, situacao, quando))
        cobranca.save(update_fields=[
            'status', 'paga_em', 'valor_pago', 'pagbank_pedido_id', 'detalhes_pagamento',
            'pagamento_duplicado', 'acerto_manual', 'atualizado_em',
        ])
        cobranca_id = cobranca.pk
        transaction.on_commit(lambda: _depois_da_baixa(cobranca_id))
    if cobranca.acerto_manual:
        logger.warning('Cobrança %s precisa de acerto manual: %s', cobranca.pk, cobranca.acerto_manual)
    return True


def _depois_da_baixa(cobranca_id: int) -> None:
    from crm.tarefas import agendar

    from .avisos import avisar_pagamento
    from .comprovante import anexar_comprovante

    agendar(anexar_comprovante, cobranca_id)
    agendar(avisar_pagamento, cobranca_id)


def _encerrar(cobranca: Cobranca, status: str) -> None:
    atualizadas = (Cobranca.objects.filter(pk=cobranca.pk, status=Cobranca.Status.PENDENTE)
                   .update(status=status, atualizado_em=timezone.now()))
    if atualizadas:
        logger.info('Cobrança %s encerrada como %s.', cobranca.pk, status)


def processar_pedido(pedido: dict, checkout_id: str = '') -> Cobranca | None:
    situacao = payloads.situacao_pedido(pedido)
    cobranca = localizar(situacao, checkout_id)
    if cobranca is None:
        logger.warning('Pedido %s do PagBank sem cobrança correspondente.', situacao.pedido_id)
        return None
    if situacao.pago:
        registrar_pagamento(cobranca, situacao)
    elif situacao.cancelado and cobranca.forma != Cobranca.Forma.CARTAO:
        _encerrar(cobranca, Cobranca.Status.EXPIRADA)
    return cobranca


def _processar_checkout(corpo: dict) -> Cobranca | None:
    cobranca = Cobranca.objects.filter(pagbank_id=corpo.get('id', '')).first()
    if cobranca and corpo.get('status') in payloads.CHECKOUT_ENCERRADO:
        _encerrar(cobranca, Cobranca.Status.EXPIRADA)
    return cobranca


def processar_notificacao(corpo: dict, produto_id: str = '', assinado: bool = True) -> Cobranca | None:
    """Pedidos são sempre consultados de novo na API. Sem assinatura, o aviso só serve de sinal para a consulta:
    não encerra checkout pelo corpo nem usa o cabeçalho `x-product-id`."""
    identificador = str(corpo.get('id') or '')
    if identificador.startswith(PREFIXO_CHECKOUT) and not corpo.get('charges'):
        return _processar_checkout(corpo) if assinado else None
    if not identificador.startswith(PREFIXO_PEDIDO):
        logger.warning('Notificação do PagBank sem pedido reconhecível: %s', identificador[:40])
        return None
    checkout_id = produto_id if assinado and produto_id.startswith(PREFIXO_CHECKOUT) else ''
    pedido = cliente.consultar_pedido(identificador)
    return processar_pedido(pedido, checkout_id)
