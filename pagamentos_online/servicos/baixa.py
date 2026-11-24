"""Baixa automática: o PagBank avisa, o sistema confere o pedido na API e dá baixa na parcela.

Nunca confia só no corpo da notificação: o pedido é sempre consultado de novo.
Processar o mesmo pagamento duas vezes não dá baixa em dobro.
"""
import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from vendas.models import ORIGEM_BAIXA_PAGBANK, Parcela

from ..models import Cobranca
from ..pagbank import cliente, payloads

logger = logging.getLogger(__name__)

PREFIXO_PEDIDO = 'ORDE_'
PREFIXO_CHECKOUT = 'CHEC_'
CAMPOS_PARCELA = ['valor_pago', 'pago', 'data_pagamento', 'origem_baixa', 'modificado_em']


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


def _credito(cobranca: Cobranca, situacao: payloads.SituacaoPedido, restante: Decimal) -> tuple[Decimal, list[str]]:
    """Quanto entra na parcela e as divergências para a equipe acertar."""
    avisos = []
    credito = cobranca.valor_parcela
    pago = situacao.valor_pago
    if pago is not None and pago < cobranca.valor_total:
        credito = min(credito, pago)
        avisos.append(f'Pago a menor: R$ {pago} de R$ {cobranca.valor_total}.')
    if credito > restante:
        avisos.append(f'Pago R$ {credito} com saldo de R$ {restante} na parcela: excedente de R$ {credito - restante}.')
        credito = restante
    return credito, avisos


def _aplicar_na_parcela(cobranca: Cobranca, situacao: payloads.SituacaoPedido, quando) -> list[str]:
    """Dá baixa no que foi pago e devolve as divergências (vazio quando está tudo certo)."""
    parcela = Parcela.objects.select_for_update().get(pk=cobranca.parcela_id)
    if parcela.pago:
        cobranca.pagamento_duplicado = True
        return ['A parcela já estava paga: estorno ou acerto manual.']
    credito, avisos = _credito(cobranca, situacao, max(parcela.valor_restante, Decimal('0')))
    parcela.valor_pago = (parcela.valor_pago or Decimal('0')) + credito
    parcela.pago = parcela.valor_restante <= 0
    parcela.data_pagamento = timezone.localdate(quando)
    parcela.origem_baixa = ORIGEM_BAIXA_PAGBANK
    parcela.save(update_fields=CAMPOS_PARCELA)
    return avisos


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
        cobranca.acerto_manual = '\n'.join(_aplicar_na_parcela(cobranca, situacao, quando))
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


def processar_notificacao(corpo: dict, produto_id: str = '') -> Cobranca | None:
    """Corpo de uma notificação já autenticada. Pedidos são consultados de novo na API."""
    identificador = str(corpo.get('id') or '')
    if identificador.startswith(PREFIXO_CHECKOUT) and not corpo.get('charges'):
        return _processar_checkout(corpo)
    if not identificador.startswith(PREFIXO_PEDIDO):
        logger.warning('Notificação do PagBank sem pedido reconhecível: %s', identificador[:40])
        return None
    checkout_id = produto_id if produto_id.startswith(PREFIXO_CHECKOUT) else ''
    pedido = cliente.consultar_pedido(identificador)
    return processar_pedido(pedido, checkout_id)
