"""Contexto do PDF do dashboard: mesmo conteúdo de `DashboardReportPDFView.get_dashboard_data`.

Diferenças em relação ao gráfico (mantidas como na view antiga):
- "vencidas" e "a vencer" não descontam pagamentos em devolução;
- desativados por loja consideram todas as vendas da loja (não só as com parcela no período);
- toda loja do recorte aparece, mesmo sem movimento.
O template usado é o mesmo da tela antiga (`dash/relatorio_pdf.html`).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone

from vendas.models import Cliente

from . import carteira
from .carteira import Periodo
from .quitados import clientes_quitados_por_loja, todos_os_clientes

TEMPLATE_PDF = 'dash/relatorio_pdf.html'
LOJA_DESCONHECIDA = 'Desconhecida'


def _lista_quitados(quitados: dict[int, set[int]], lojas_por_id: dict[int, str]) -> list[dict]:
    """Nome de cada cliente uma vez, com as lojas dos financiamentos quitados."""
    lojas_por_cliente: dict[int, set[str]] = defaultdict(set)
    for loja_id, clientes in quitados.items():
        for cliente_id in clientes:
            lojas_por_cliente[cliente_id].add(lojas_por_id.get(loja_id, LOJA_DESCONHECIDA))
    nomes = dict(Cliente.objects.filter(id__in=lojas_por_cliente).values_list('id', 'nome'))
    lista = [
        {'nome': nomes[cliente_id], 'lojas': ', '.join(sorted(lojas, key=str.casefold))}
        for cliente_id, lojas in lojas_por_cliente.items()
        if cliente_id in nomes
    ]
    return sorted(lista, key=lambda cliente: cliente['nome'].casefold())


def _dados_da_loja(loja, parcelas_periodo: list, parcelas_loja: list, periodo: Periodo, hoje: date) -> dict:
    vencidas = [p for p in parcelas_periodo if carteira.vencida(p, hoje, considerar_devolucao=False)]
    pagas = [p for p in parcelas_periodo if carteira.paga(p)]
    a_vencer = [p for p in parcelas_periodo if carteira.a_vencer(p, hoje, considerar_devolucao=False)]
    desativadas = [
        p for p in parcelas_loja
        if carteira.desativada_em_aberto(p) and carteira.vencimento_no_periodo(p, periodo)
    ]
    desat_vencidas = [p for p in desativadas if p.data_vencimento < hoje]
    desat_a_vencer = [p for p in desativadas if p.data_vencimento >= hoje]
    totais = {
        'total_pagas': sum((p.valor_pago_efetivo for p in pagas), Decimal(0)),
        'total_vencidas': sum((p.valor for p in vencidas), Decimal(0)),
        'total_a_vencer': sum((p.valor for p in a_vencer), Decimal(0)),
        'total_desativados_vencidas': sum((p.valor for p in desat_vencidas), Decimal(0)),
        'total_desativados_a_vencer': sum((p.valor for p in desat_a_vencer), Decimal(0)),
    }
    return {
        'loja': loja,
        'total_parcelas': len(vencidas) + len(pagas) + len(a_vencer),
        'parcelas_pagas': len(pagas),
        'parcelas_vencidas': len(vencidas),
        'parcelas_a_vencer': len(a_vencer),
        'qtd_desativados_vencidas': len(desat_vencidas),
        'qtd_desativados_a_vencer': len(desat_a_vencer),
        'valor_total_parcelas': sum(totais.values(), Decimal(0)),
        'clientes_vencidos_ids': {p.pagamento.venda.cliente_id for p in vencidas if p.pagamento.venda.cliente_id},
        **totais,
    }


def _chave_unica(nome: str, loja_id: int, usados: set[str]) -> str:
    """Nome da loja como chave; se dois nomes coincidirem, o segundo leva o id (a antiga sobrescrevia)."""
    return nome if nome not in usados else f'{nome} ({loja_id})'


def contexto_relatorio_dashboard(lojas: QuerySet, periodo: Periodo, usuario, hoje: date | None = None) -> dict:
    hoje = hoje or timezone.now().date()
    vendas = carteira.vendas_das_lojas(lojas)
    parcelas = carteira.parcelas_ipx(vendas)
    do_periodo = [p for p in parcelas if carteira.no_periodo(p, periodo)]
    periodo_por_loja, todas_por_loja = defaultdict(list), defaultdict(list)
    for parcela in do_periodo:
        periodo_por_loja[carteira.loja_da_parcela(parcela)].append(parcela)
    for parcela in parcelas:
        todas_por_loja[carteira.loja_da_parcela(parcela)].append(parcela)

    quitados = clientes_quitados_por_loja({p.pagamento_id for p in do_periodo})
    vendas_periodo = carteira.vendas_e_repasses_por_loja(carteira.vendas_do_periodo(vendas, periodo))
    lojas_lista = list(lojas)

    dados_por_loja, usados, clientes_vencidos = {}, set(), set()
    for loja in sorted(lojas_lista, key=lambda item: (item.nome.lower(), item.pk)):
        dados = _dados_da_loja(loja, periodo_por_loja.get(loja.pk, []), todas_por_loja.get(loja.pk, []), periodo, hoje)
        vencidos_loja = dados.pop('clientes_vencidos_ids')
        clientes_vencidos |= vencidos_loja
        qtd_vendas, repasses = vendas_periodo.get(loja.pk, (0, Decimal(0)))
        chave = _chave_unica(loja.nome, loja.pk, usados)
        usados.add(chave)
        dados_por_loja[chave] = {
            **dados,
            'total_vendas': qtd_vendas,
            'total_repasses': repasses,
            'clientes_vencidos': len(vencidos_loja),
            'clientes_quitados': len(quitados.get(loja.pk, set())),
        }

    return {
        'dados_por_loja': dados_por_loja,
        'clientes_vencidos': len(clientes_vencidos),
        'clientes_quitados': len(todos_os_clientes(quitados)),
        'clientes_quitados_lista': _lista_quitados(quitados, {loja.pk: loja.nome for loja in lojas_lista}),
        'data_geracao': timezone.now(),
        'usuario': usuario,
    }
