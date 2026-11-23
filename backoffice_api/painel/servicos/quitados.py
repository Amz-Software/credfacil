"""Clientes com financiamento IPX quitado (spec `dashboard-clientes-quitados`).

Extraído de `vendas/views/relatorios.py:_clientes_quitados_por_loja` (a tela Django
continua usando a dela); a regra é a mesma, linha a linha.
"""
from collections import defaultdict
from collections.abc import Iterable

from django.db.models import Count, F, Q

from vendas.models import Pagamento

TIPO_CREDFACIL = 'IPX'


def clientes_quitados_por_loja(pagamento_ids: Iterable[int]) -> dict[int, set[int]]:
    """IDs de clientes com pagamento IPX integralmente quitado, por loja da venda.

    `pagamento_ids` deve conter só pagamentos com ao menos uma parcela no período
    escolhido. A quitação é avaliada sobre todas as parcelas do pagamento, e não
    apenas sobre as do período.
    """
    ids = set(pagamento_ids)
    clientes_por_loja: dict[int, set[int]] = defaultdict(set)
    if not ids:
        return clientes_por_loja

    pagamentos_quitados = (
        Pagamento.objects.filter(
            id__in=ids,
            tipo_pagamento__nome=TIPO_CREDFACIL,
            venda__cliente_id__isnull=False,
        )
        .annotate(
            total_parcelas=Count('parcelas_pagamento', distinct=True),
            parcelas_pagas=Count(
                'parcelas_pagamento',
                filter=Q(parcelas_pagamento__pago=True),
                distinct=True,
            ),
        )
        .filter(total_parcelas__gt=0, total_parcelas=F('parcelas_pagas'))
        .values_list('venda__loja_id', 'venda__cliente_id')
        .distinct()
    )
    for loja_id, cliente_id in pagamentos_quitados:
        clientes_por_loja[loja_id].add(cliente_id)
    return clientes_por_loja


def todos_os_clientes(clientes_por_loja: dict[int, set[int]]) -> set[int]:
    """Clientes únicos (um cliente com financiamentos em lojas diferentes conta uma vez)."""
    return set().union(*clientes_por_loja.values()) if clientes_por_loja else set()
