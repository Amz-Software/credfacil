"""Rede de segurança do webhook: consulta as cobranças pendentes e encerra as vencidas.

Roda no `crm_rotinas` (a cada minuto); cada cobrança é consultada no máximo a cada INTERVALO.
O checkout de cartão não tem consulta de pedido: depende da notificação e só expira aqui.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from ..models import Cobranca, RegistroPagBank
from ..pagbank import cliente
from .baixa import processar_pedido

logger = logging.getLogger(__name__)

INTERVALO = timedelta(minutes=5)
ESPERA_INICIAL = timedelta(minutes=2)
LIMITE_POR_RODADA = 50
# Depois de expirar ainda pode chegar a compensação: o boleto leva dias úteis.
TOLERANCIA = {
    Cobranca.Forma.PIX: timedelta(hours=1),
    Cobranca.Forma.CARTAO: timedelta(hours=1),
    Cobranca.Forma.BOLETO: timedelta(days=5),
}
GUARDA_REGISTROS = timedelta(days=180)


def _expirar_vencidas(agora) -> int:
    total = 0
    for forma, tolerancia in TOLERANCIA.items():
        total += (Cobranca.objects
                  .filter(status=Cobranca.Status.PENDENTE, forma=forma, expira_em__lt=agora - tolerancia)
                  .update(status=Cobranca.Status.EXPIRADA, atualizado_em=agora))
    return total


def _consultar_pendentes(agora) -> int:
    candidatas = list(
        Cobranca.objects
        .filter(status=Cobranca.Status.PENDENTE, forma__in=[Cobranca.Forma.PIX, Cobranca.Forma.BOLETO],
                criado_em__lt=agora - ESPERA_INICIAL, atualizado_em__lt=agora - INTERVALO)
        .exclude(pagbank_id='')
        .order_by('atualizado_em')[:LIMITE_POR_RODADA]
    )
    consultadas = 0
    for cobranca in candidatas:
        Cobranca.objects.filter(pk=cobranca.pk).update(atualizado_em=agora)
        try:
            processar_pedido(cliente.consultar_pedido(cobranca.pagbank_id, cobranca=cobranca))
        except cliente.ErroPagBank:
            logger.warning('Conciliação: PagBank não respondeu para a cobrança %s.', cobranca.pk)
            break  # fora do ar: tenta de novo na próxima rodada
        consultadas += 1
    return consultadas


def conciliar() -> dict:
    if not cliente.configurado():
        return {'pulado': 'sem PAGBANK_TOKEN'}
    agora = timezone.now()
    consultadas = _consultar_pendentes(agora)
    expiradas = _expirar_vencidas(agora)
    apagados, _ = RegistroPagBank.objects.filter(criado_em__lt=agora - GUARDA_REGISTROS).delete()
    return {'consultadas': consultadas, 'expiradas': expiradas, 'registros_apagados': apagados}
