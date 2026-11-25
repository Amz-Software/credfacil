"""Condições de status por parcela (EXISTS), equivalentes às de `with_status_flags`.

`with_status_flags` agrega todas as parcelas com GROUP BY e, em listas grandes,
custava segundos por requisição. Estas condições filtram sem agregar.
"""
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from vendas.models import Parcela


def existe_parcela(**filtros) -> Exists:
    return Exists(Parcela.objects.filter(pagamento=OuterRef('pk'), **filtros))


def com_parcela_atrasada() -> Exists:
    return existe_parcela(pago=False, data_vencimento__lt=timezone.localdate())


def todas_parcelas_pagas() -> Q:
    return Q(~existe_parcela(pago=False))


def com_pagamento_pendente() -> Q:
    """Alguma parcela em aberto e nenhuma atrasada."""
    return Q(existe_parcela(pago=False)) & ~Q(com_parcela_atrasada())
