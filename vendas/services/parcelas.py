"""Datas e geração das parcelas de um pagamento."""
import calendar
from datetime import date

from django.utils import timezone

from vendas.models import Parcela

DIAS_MAXIMOS_ATE_PRIMEIRA_PARCELA = 30
MESES_AVALIADOS = 3


def _somar_meses(ano: int, mes: int, meses: int) -> tuple[int, int]:
    deslocamento = mes - 1 + meses
    return ano + deslocamento // 12, deslocamento % 12 + 1


def _dia_no_mes(ano: int, mes: int, dia: int) -> date:
    """Data com o dia pedido ou o último dia do mês, se ele não existir (30/02 → 28/02)."""
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def calcular_data_primeira_parcela(dia_pagamento, hoje: date | None = None) -> date | None:
    """Data mais distante com o dia escolhido (1, 10 ou 20) em até 30 dias após `hoje`.

    Devolve None se nenhuma data dos próximos meses cair nessa janela.
    """
    hoje = hoje or timezone.now().date()
    dia = int(dia_pagamento)
    candidatas = (
        _dia_no_mes(*_somar_meses(hoje.year, hoje.month, i), dia)
        for i in range(MESES_AVALIADOS)
    )
    validas = [
        data for data in candidatas
        if 0 < (data - hoje).days <= DIAS_MAXIMOS_ATE_PRIMEIRA_PARCELA
    ]
    return max(validas, default=None)


def criar_parcelas(pagamento, loja) -> list[Parcela]:
    """Recria as parcelas do pagamento mantendo o dia da primeira parcela em todos os meses."""
    Parcela.objects.filter(pagamento=pagamento).delete()
    primeira = pagamento.data_primeira_parcela
    return [
        Parcela.objects.create(
            loja=loja,
            pagamento=pagamento,
            numero_parcela=numero,
            valor=pagamento.valor_parcela,
            data_vencimento=_dia_no_mes(
                *_somar_meses(primeira.year, primeira.month, numero - 1), primeira.day
            ),
            criado_por=pagamento.criado_por,
            modificado_por=pagamento.modificado_por,
        )
        for numero in range(1, pagamento.parcelas + 1)
    ]
