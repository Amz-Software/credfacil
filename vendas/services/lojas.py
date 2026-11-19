"""Regras de loja: QR code do aplicativo e calendário de repasses ao logista."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from financeiro.models import Repasse
from vendas.models import Loja, Venda

from .erros import ErroDeNegocio

LIMITE_MESES_REPASSE = 6
STATUS_REPASSE_PARCIAL = 'parcial'


def replicar_qr_code_aplicativo(loja_origem: Loja) -> int:
    """Copia QR code e código do aplicativo da loja para todas as outras. Devolve quantas mudaram."""
    if not loja_origem.qr_code_aplicativo or loja_origem.codigo_aplicativo is None:
        raise ErroDeNegocio('Loja não possui QR Code ou código do aplicativo configurado.')
    destinos = Loja.objects.exclude(id=loja_origem.id)
    total = 0
    for loja in destinos:
        loja.qr_code_aplicativo = loja_origem.qr_code_aplicativo
        loja.codigo_aplicativo = loja_origem.codigo_aplicativo
        loja.save(update_fields=['qr_code_aplicativo', 'codigo_aplicativo'])
        total += 1
    return total


@dataclass(frozen=True)
class PeriodoRepasse:
    data: date
    inicio: date
    fim: date


def _periodo(ano: int, mes: int, dia: int) -> PeriodoRepasse:
    """Competência de cada data de repasse: 06 → 26/mês anterior a 05; 16 → 06 a 15; 26 → 16 a 25."""
    data = date(ano, mes, dia)
    if dia == 6:
        fim = date(ano, mes, 5)
        inicio = (date(ano, mes, 1) - timedelta(days=1)).replace(day=26)
        return PeriodoRepasse(data, inicio, fim)
    if dia == 16:
        return PeriodoRepasse(data, date(ano, mes, 6), date(ano, mes, 15))
    return PeriodoRepasse(data, date(ano, mes, 16), date(ano, mes, 25))


def periodos_de_repasse(hoje: date, meses_atras: int = 0,
                        limite_meses: int = LIMITE_MESES_REPASSE) -> list[PeriodoRepasse]:
    """Datas de repasse (dias 6, 16 e 26) do mês mais antigo até o atual, em ordem."""
    periodos = []
    for delta in range(min(meses_atras, limite_meses), -1, -1):
        ano, mes = hoje.year, hoje.month - delta
        while mes <= 0:
            mes += 12
            ano -= 1
        periodos.extend(_periodo(ano, mes, dia) for dia in Loja.REPASSES_DIAS)
    return periodos


def _vendas_por_dia(loja_ids, inicio: date, fim: date) -> dict:
    """{loja_id: [(dia_local, repasse_logista), ...]} das vendas ativas no intervalo."""
    vendas = Venda.objects.filter(
        loja_id__in=loja_ids, is_deleted=False,
        data_venda__date__gte=inicio, data_venda__date__lte=fim,
    ).values_list('loja_id', 'data_venda', 'repasse_logista')
    por_loja = defaultdict(list)
    for loja_id, data_venda, repasse in vendas:
        por_loja[loja_id].append((timezone.localtime(data_venda).date(), repasse))
    return por_loja


def _repasses_registrados(loja_ids, datas) -> dict:
    """{(loja_id, data): [Repasse, ...]} dos repasses lançados nas datas do calendário."""
    registrados = defaultdict(list)
    for repasse in Repasse.objects.filter(loja_id__in=loja_ids, data__date__in=datas):
        registrados[(repasse.loja_id, timezone.localtime(repasse.data).date())].append(repasse)
    return registrados


def _marcar_parciais(repasses, valor_devido: Decimal) -> None:
    # Regra herdada: repasse lançado com valor menor que o devido vira 'parcial'.
    for repasse in repasses:
        if repasse.valor < valor_devido:
            repasse.status = STATUS_REPASSE_PARCIAL
            repasse.save()


def status_repasses_por_loja(lojas, meses_atras: int = 0, hoje: date | None = None,
                             limite_meses: int = LIMITE_MESES_REPASSE) -> dict:
    """Situação dos repasses de várias lojas com um número fixo de consultas.

    Devolve {loja_id: (resultados, atrasados)} no mesmo formato de
    `Loja.get_repasses_status`: períodos sem venda são omitidos e `atrasados`
    conta os repasses vencidos ainda não lançados.
    """
    hoje = hoje or date.today()
    loja_ids = [loja.id for loja in lojas]
    periodos = periodos_de_repasse(hoje, meses_atras, limite_meses)
    if not loja_ids or not periodos:
        return {loja_id: ([], 0) for loja_id in loja_ids}

    vendas = _vendas_por_dia(loja_ids, periodos[0].inicio, periodos[-1].fim)
    registrados = _repasses_registrados(loja_ids, [p.data for p in periodos])
    status = {}
    for loja_id in loja_ids:
        resultados = []
        for periodo in periodos:
            repasses_periodo = [
                valor for dia, valor in vendas.get(loja_id, [])
                if periodo.inicio <= dia <= periodo.fim
            ]
            if not repasses_periodo:
                continue
            valor = sum(repasses_periodo, Decimal('0.00'))
            lancados = registrados.get((loja_id, periodo.data), [])
            _marcar_parciais(lancados, valor)
            resultados.append({
                'data': periodo.data,
                'inicio_periodo': periodo.inicio,
                'fim_periodo': periodo.fim,
                'qtd_vendas': len(repasses_periodo),
                'valor_total_repasse': valor,
                'feito': bool(lancados),
            })
        atrasados = sum(1 for r in resultados if not r['feito'] and r['data'] < hoje)
        status[loja_id] = (resultados, atrasados)
    return status
