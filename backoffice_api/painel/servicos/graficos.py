"""Dashboard de gráficos: mesmos números de `vendas/views/index.py:GraficoTemplateView`.

Regras reproduzidas da view antiga (inclusive as particularidades):
- parcelas IPX entram pelo período da data-base (pagamento, se paga; senão vencimento);
- "vencidas" e "a vencer" ignoram pagamentos em devolução; "pagas" não;
- desativados e cobrança por loja filtram pelo vencimento no período; o total geral
  de cobrança não filtra por data (como hoje);
- repasses e quantidade de vendas seguem a data da venda.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import QuerySet
from django.utils import timezone

from vendas.models import Pagamento

from . import carteira
from .carteira import Periodo
from .quitados import clientes_quitados_por_loja, todos_os_clientes

LOJA_DESCONHECIDA = 'Desconhecida'
SITUACOES_MENSAIS = (('pago', 'Pago'), ('vencido', 'Vencido'), ('a_vencer', 'A Vencer'))


@dataclass
class Totais:
    """Quantidades e valores de um recorte (geral ou de uma loja)."""

    qtd_pagas: int = 0
    qtd_vencidas: int = 0
    qtd_a_vencer: int = 0
    total_pagas: Decimal = Decimal(0)
    total_vencidas: Decimal = Decimal(0)
    total_a_vencer: Decimal = Decimal(0)
    qtd_desativados_vencidas: int = 0
    qtd_desativados_a_vencer: int = 0
    total_desativados_vencidas: Decimal = Decimal(0)
    total_desativados_a_vencer: Decimal = Decimal(0)
    qtd_cobranca_vencidas: int = 0
    qtd_cobranca_a_vencer: int = 0
    total_cobranca_vencidas: Decimal = Decimal(0)
    total_cobranca_a_vencer: Decimal = Decimal(0)
    mensal: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(Decimal)))

    @property
    def total_geral(self) -> Decimal:
        return (
            self.total_pagas + self.total_vencidas + self.total_a_vencer
            + self.total_desativados_vencidas + self.total_desativados_a_vencer
            + self.total_cobranca_vencidas + self.total_cobranca_a_vencer
        )


def _somar_classificacao(totais: Totais, parcela, hoje: date) -> bool:
    """Classifica a parcela do período; devolve True se ela estava vencida."""
    mes = parcela.data_vencimento.strftime('%Y-%m')
    if carteira.paga(parcela):
        totais.qtd_pagas += 1
        totais.total_pagas += parcela.valor_pago_efetivo
        totais.mensal[mes]['pago'] += parcela.valor_pago_efetivo
    elif carteira.vencida(parcela, hoje):
        totais.qtd_vencidas += 1
        totais.total_vencidas += parcela.valor
        totais.mensal[mes]['vencido'] += parcela.valor
        return True
    elif carteira.a_vencer(parcela, hoje):
        totais.qtd_a_vencer += 1
        totais.total_a_vencer += parcela.valor
        totais.mensal[mes]['a_vencer'] += parcela.valor
    return False


def _somar_situacao(totais: Totais, prefixo: str, parcela, hoje: date) -> None:
    chave = 'vencidas' if parcela.data_vencimento < hoje else 'a_vencer'
    setattr(totais, f'qtd_{prefixo}_{chave}', getattr(totais, f'qtd_{prefixo}_{chave}') + 1)
    setattr(totais, f'total_{prefixo}_{chave}', getattr(totais, f'total_{prefixo}_{chave}') + parcela.valor)


@dataclass
class ResultadoGraficos:
    geral: Totais
    por_loja: dict[int, Totais]
    nomes_lojas: dict[int, str]
    total_vendas: int
    total_parcelas: int
    clientes_vencidos: int
    clientes_quitados: int
    total_repasses: Decimal
    repasses_por_loja: dict[int, Decimal]
    cobranca_geral: Totais
    total_pagamentos_desativados: int
    total_pagamentos_cobranca: int
    incluir_mensal: bool


def calcular_graficos(
    lojas: QuerySet, periodo: Periodo, *, incluir_mensal: bool, hoje: date | None = None, comodato: bool | None = None,
) -> ResultadoGraficos:
    hoje = hoje or timezone.now().date()
    vendas = carteira.vendas_das_lojas(lojas, comodato)
    parcelas = carteira.parcelas_ipx(vendas)
    do_periodo = [p for p in parcelas if carteira.no_periodo(p, periodo)]
    vendas_validas = {p.pagamento.venda_id for p in do_periodo}

    geral, por_loja, clientes_vencidos = Totais(), defaultdict(Totais), set()
    for parcela in do_periodo:
        loja_id = carteira.loja_da_parcela(parcela)
        _somar_classificacao(geral, parcela, hoje)
        if _somar_classificacao(por_loja[loja_id], parcela, hoje) and parcela.pagamento.venda.cliente_id:
            clientes_vencidos.add(parcela.pagamento.venda.cliente_id)

    cobranca_geral = Totais()
    for parcela in parcelas:
        if parcela.pagamento.venda_id not in vendas_validas:
            continue
        loja_id = carteira.loja_da_parcela(parcela)
        dentro = carteira.vencimento_no_periodo(parcela, periodo)
        if carteira.desativada_em_aberto(parcela) and dentro:
            _somar_situacao(geral, 'desativados', parcela, hoje)
            _somar_situacao(por_loja[loja_id], 'desativados', parcela, hoje)
        if carteira.em_cobranca_em_aberto(parcela):
            _somar_situacao(cobranca_geral, 'cobranca', parcela, hoje)
            if dentro:
                _somar_situacao(por_loja[loja_id], 'cobranca', parcela, hoje)

    quitados = clientes_quitados_por_loja({p.pagamento_id for p in do_periodo})
    vendas_periodo = carteira.vendas_e_repasses_por_loja(carteira.vendas_do_periodo(vendas, periodo))
    pagamentos_ipx = Pagamento.objects.filter(venda_id__in=vendas_validas, tipo_pagamento__nome=carteira.TIPO_CREDFACIL)
    return ResultadoGraficos(
        geral=geral,
        por_loja=dict(por_loja),
        nomes_lojas=dict(lojas.values_list('id', 'nome')),
        total_vendas=sum(qtd for qtd, _ in vendas_periodo.values()),
        total_parcelas=len(do_periodo),
        clientes_vencidos=len(clientes_vencidos),
        clientes_quitados=len(todos_os_clientes(quitados)),
        total_repasses=sum((soma for _, soma in vendas_periodo.values()), Decimal(0)),
        repasses_por_loja={loja_id: soma for loja_id, (_, soma) in vendas_periodo.items()},
        cobranca_geral=cobranca_geral,
        total_pagamentos_desativados=pagamentos_ipx.filter(desativado=True).count(),
        total_pagamentos_cobranca=pagamentos_ipx.filter(flag_atrasado=True).count(),
        incluir_mensal=incluir_mensal,
    )


# ── Formatação para a API ──────────────────────────────────────────────────

def _nome(resultado: ResultadoGraficos, loja_id: int | None) -> str:
    return resultado.nomes_lojas.get(loja_id, LOJA_DESCONHECIDA)


def _lojas_ordenadas(resultado: ResultadoGraficos, ids) -> list[int | None]:
    return sorted(ids, key=lambda loja_id: (_nome(resultado, loja_id).lower(), loja_id or 0))


def resumo_geral(resultado: ResultadoGraficos) -> dict:
    geral, cobranca = resultado.geral, resultado.cobranca_geral
    return {
        'total_vendas': resultado.total_vendas,
        'total_parcelas': resultado.total_parcelas,
        'valor_total_parcelas': geral.total_pagas + geral.total_vencidas + geral.total_a_vencer,
        'total_repasses': resultado.total_repasses,
        'parcelas_pagas': geral.qtd_pagas,
        'valor_pago': geral.total_pagas,
        'parcelas_vencidas': geral.qtd_vencidas,
        'valor_vencido': geral.total_vencidas,
        'parcelas_a_vencer': geral.qtd_a_vencer,
        'valor_a_vencer': geral.total_a_vencer,
        'clientes_vencidos': resultado.clientes_vencidos,
        'clientes_quitados': resultado.clientes_quitados,
        'cobranca': {
            'total_pagamentos': resultado.total_pagamentos_cobranca,
            'parcelas_vencidas': cobranca.qtd_cobranca_vencidas,
            'valor_vencido': cobranca.total_cobranca_vencidas,
            'parcelas_a_vencer': cobranca.qtd_cobranca_a_vencer,
            'valor_a_vencer': cobranca.total_cobranca_a_vencer,
        },
        'desativados': {
            'total_pagamentos': resultado.total_pagamentos_desativados,
            'parcelas_vencidas': geral.qtd_desativados_vencidas,
            'valor_vencido': geral.total_desativados_vencidas,
            'parcelas_a_vencer': geral.qtd_desativados_a_vencer,
            'valor_a_vencer': geral.total_desativados_a_vencer,
        },
    }


def repasses_por_loja(resultado: ResultadoGraficos) -> list[dict]:
    ids = _lojas_ordenadas(resultado, resultado.repasses_por_loja)
    return [
        {'loja': {'id': loja_id, 'nome': _nome(resultado, loja_id)}, 'valor': resultado.repasses_por_loja[loja_id]}
        for loja_id in ids
    ]


def _serie(id_serie: str, rotulo: str, percentuais: list, valores: list) -> dict:
    return {'id': id_serie, 'rotulo': rotulo, 'percentuais': percentuais, 'valores': valores}


FATIAS_POR_LOJA = (
    ('pagas', '% Pagas', lambda t: t.total_pagas),
    ('vencidas', '% Vencidas', lambda t: t.total_vencidas),
    ('desativados', '% Desativados', lambda t: t.total_desativados_vencidas + t.total_desativados_a_vencer),
    ('cobrancas', '% Cobranças', lambda t: t.total_cobranca_vencidas + t.total_cobranca_a_vencer),
)


def serie_por_loja(resultado: ResultadoGraficos) -> dict:
    """Balanço por loja: percentuais empilhados + valores em R$ de cada fatia."""
    ids = _lojas_ordenadas(resultado, resultado.por_loja)
    totais = [resultado.por_loja[i] for i in ids]
    series = [
        _serie(
            id_serie,
            rotulo,
            [float(carteira.percentual(parte(t), t.total_geral)) for t in totais],
            [float(parte(t)) for t in totais],
        )
        for id_serie, rotulo, parte in FATIAS_POR_LOJA
    ]
    return {
        'lojas': [{'id': i, 'nome': _nome(resultado, i)} for i in ids],
        'rotulos': [_nome(resultado, i) for i in ids],
        'totais': [float(t.total_geral) for t in totais],
        'series': series,
    }


def _percentual_inteiro(parte: Decimal, total: Decimal) -> int:
    """Como o gráfico antigo (Math.round): meio para cima."""
    if not total:
        return 0
    return int((parte / total * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def serie_por_loja_mes(resultado: ResultadoGraficos) -> dict | None:
    """Balanço mensal (por vencimento); só quando o recorte é de uma loja, como na tela antiga."""
    if not resultado.incluir_mensal:
        return None
    com_mes = {i: t.mensal for i, t in resultado.por_loja.items() if t.mensal}
    meses = sorted({mes for mensal in com_mes.values() for mes in mensal})
    series = []
    for loja_id in _lojas_ordenadas(resultado, com_mes):
        mensal = com_mes[loja_id]
        totais = [sum(mensal[m].values(), Decimal(0)) if m in mensal else Decimal(0) for m in meses]
        for chave, rotulo in SITUACOES_MENSAIS:
            valores = [mensal[m][chave] if m in mensal else Decimal(0) for m in meses]
            series.append({
                'loja': {'id': loja_id, 'nome': _nome(resultado, loja_id)},
                'situacao': chave,
                'rotulo': f'{_nome(resultado, loja_id)} - {rotulo}',
                'percentuais': [_percentual_inteiro(v, t) for v, t in zip(valores, totais)],
                'valores': [float(v) for v in valores],
                'totais': [float(t) for t in totais],
            })
    return {'rotulos': meses, 'series': series}


def formatar_graficos(resultado: ResultadoGraficos) -> dict:
    return {
        'resumo': resumo_geral(resultado),
        'repasses_por_loja': repasses_por_loja(resultado),
        'por_loja': serie_por_loja(resultado),
        'por_loja_mes': serie_por_loja_mes(resultado),
    }
