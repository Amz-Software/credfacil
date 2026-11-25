"""Base comum do dashboard de gráficos e do relatório PDF do dashboard.

Reproduz as regras de `vendas/views/index.py` (`GraficoTemplateView` e
`DashboardReportPDFView`), que só existiam dentro das views: quais parcelas IPX
entram no período, como cada uma é classificada e como as vendas do período
somam repasses. As parcelas são lidas numa só consulta (a view antiga fazia
consultas por venda).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from django.db.models import Count, QuerySet, Sum
from django.utils import timezone

from vendas.models import Parcela, Venda

TIPO_CREDFACIL = 'IPX'
FIM_DO_DIA = time(23, 59, 59)


@dataclass(frozen=True)
class Periodo:
    inicio: date | None = None
    fim: date | None = None


def vendas_das_lojas(lojas: QuerySet, comodato: bool | None = None) -> QuerySet:
    """Vendas ativas das lojas; `comodato` True/False restringe às de comodato ou às comuns."""
    vendas = Venda.objects.filter(is_deleted=False, loja__in=lojas)
    return vendas if comodato is None else vendas.filter(comodato=comodato)


def vendas_do_periodo(vendas: QuerySet, periodo: Periodo) -> QuerySet:
    """Vendas pela data da venda: de 00:00 do início até 23:59:59 do fim."""
    if periodo.inicio:
        vendas = vendas.filter(data_venda__gte=timezone.make_aware(datetime.combine(periodo.inicio, time.min)))
    if periodo.fim:
        vendas = vendas.filter(data_venda__lte=timezone.make_aware(datetime.combine(periodo.fim, FIM_DO_DIA)))
    return vendas


def vendas_e_repasses_por_loja(vendas_periodo: QuerySet) -> dict[int, tuple[int, Decimal]]:
    """{loja_id: (quantidade de vendas, soma de repasse_logista)} das vendas do período."""
    linhas = vendas_periodo.values('loja_id').annotate(qtd=Count('id'), soma=Sum('repasse_logista'))
    return {linha['loja_id']: (linha['qtd'], linha['soma'] or Decimal(0)) for linha in linhas}


@dataclass(frozen=True)
class VendaCarteira:
    id: int
    loja_id: int | None
    cliente_id: int | None


@dataclass(frozen=True)
class PagamentoCarteira:
    id: int
    venda_id: int
    devolucao: bool
    desativado: bool
    flag_atrasado: bool
    venda: VendaCarteira


@dataclass(frozen=True)
class ParcelaCarteira:
    """Só o que o dashboard e o PDF leem de `Parcela` (mesmos nomes de atributo).

    Instanciar dezenas de milhares de models completos (com pagamento e venda)
    custava vários segundos por requisição em produção.
    """

    id: int
    pagamento_id: int
    valor: Decimal
    valor_pago: Decimal | None
    pago: bool
    pagamento_efetuado: bool
    data_vencimento: date
    data_pagamento: date | None
    pagamento: PagamentoCarteira

    @property
    def valor_pago_efetivo(self) -> Decimal:
        """Igual a `Parcela.valor_pago_efetivo`."""
        if self.valor_pago not in (None, 0):
            return self.valor_pago
        return self.valor


CAMPOS_PARCELA_CARTEIRA = (
    'id', 'pagamento_id', 'valor', 'valor_pago', 'pago', 'pagamento_efetuado', 'data_vencimento', 'data_pagamento',
    'pagamento__venda_id', 'pagamento__devolucao', 'pagamento__desativado', 'pagamento__flag_atrasado',
    'pagamento__venda__loja_id', 'pagamento__venda__cliente_id',
)


def _parcela_da_linha(linha: tuple, pagamentos: dict) -> ParcelaCarteira:
    (pk, pagamento_id, valor, valor_pago, pago, efetuado, vencimento, data_pagamento,
     venda_id, devolucao, desativado, flag_atrasado, loja_id, cliente_id) = linha
    pagamento = pagamentos.get(pagamento_id)
    if pagamento is None:
        venda = VendaCarteira(venda_id, loja_id, cliente_id)
        pagamento = PagamentoCarteira(pagamento_id, venda_id, devolucao, desativado, flag_atrasado, venda)
        pagamentos[pagamento_id] = pagamento
    return ParcelaCarteira(pk, pagamento_id, valor, valor_pago, pago, efetuado, vencimento, data_pagamento, pagamento)


def parcelas_ipx(vendas: QuerySet) -> list[ParcelaCarteira]:
    """Todas as parcelas IPX das vendas, com os dados de pagamento e venda que as regras usam."""
    linhas = (
        Parcela.objects.filter(pagamento__venda__in=vendas, pagamento__tipo_pagamento__nome=TIPO_CREDFACIL)
        .order_by('pagamento__venda_id', 'id')
        .values_list(*CAMPOS_PARCELA_CARTEIRA)
    )
    pagamentos: dict[int, PagamentoCarteira] = {}
    return [_parcela_da_linha(linha, pagamentos) for linha in linhas]


def loja_da_parcela(parcela: ParcelaCarteira) -> int | None:
    return parcela.pagamento.venda.loja_id


def no_periodo(parcela: ParcelaCarteira, periodo: Periodo) -> bool:
    """Data-base: a do pagamento, se a parcela está paga; senão a do vencimento."""
    base = parcela.data_pagamento if (parcela.pago and parcela.data_pagamento) else parcela.data_vencimento
    if not base:
        return True
    if periodo.inicio and base < periodo.inicio:
        return False
    return not (periodo.fim and base > periodo.fim)


def vencimento_no_periodo(parcela: ParcelaCarteira, periodo: Periodo) -> bool:
    if periodo.inicio and parcela.data_vencimento < periodo.inicio:
        return False
    return not (periodo.fim and parcela.data_vencimento > periodo.fim)


def paga(parcela: ParcelaCarteira) -> bool:
    return parcela.pago and not parcela.pagamento_efetuado


def _em_aberto(parcela: ParcelaCarteira, considerar_devolucao: bool) -> bool:
    if parcela.pago or parcela.pagamento_efetuado:
        return False
    return not (considerar_devolucao and parcela.pagamento.devolucao)


def vencida(parcela: ParcelaCarteira, hoje: date, considerar_devolucao: bool = True) -> bool:
    """Em aberto e com vencimento passado. O gráfico ignora pagamentos em devolução; o PDF não."""
    return _em_aberto(parcela, considerar_devolucao) and parcela.data_vencimento < hoje


def a_vencer(parcela: ParcelaCarteira, hoje: date, considerar_devolucao: bool = True) -> bool:
    return _em_aberto(parcela, considerar_devolucao) and parcela.data_vencimento >= hoje


def desativada_em_aberto(parcela: ParcelaCarteira) -> bool:
    return parcela.pagamento.desativado and not parcela.pago


def em_cobranca_em_aberto(parcela: ParcelaCarteira) -> bool:
    return parcela.pagamento.flag_atrasado and not parcela.pago


def agrupar_por_venda(parcelas: list[ParcelaCarteira]) -> dict[int, list[ParcelaCarteira]]:
    por_venda: dict[int, list[ParcelaCarteira]] = defaultdict(list)
    for parcela in parcelas:
        por_venda[parcela.pagamento.venda_id].append(parcela)
    return por_venda


def percentual(parte, total) -> Decimal:
    """Mesmo arredondamento da view antiga: round(parte / total * 100, 2)."""
    if not total:
        return Decimal(0)
    return round(Decimal(parte) / Decimal(total) * 100, 2)
