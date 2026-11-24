"""Relatório de vendas: mesmo conteúdo de `FolhaRelatorioVendasView` (vendas/views/relatorios.py).

Os valores por venda vêm de subconsultas que reproduzem as propriedades do modelo
`Venda` (`valor_total_venda`, `valor_entrada_cliente`, `pagamentos_valor_total`,
`qtd_total_parcelas`, `juros`), para não consultar o banco venda a venda.
Os testes conferem que os números batem com as propriedades do modelo.
"""
from decimal import Decimal

from django.db.models import Exists, F, IntegerField, OuterRef, Prefetch, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from vendas.models import AnaliseCreditoCliente, Pagamento, PreAnaliseRapida, ProdutoVenda, Venda

from .comum import (
    EscopoRelatorio,
    filtrar_comodato,
    filtro_periodo,
    rotulo_status_analise,
    separar_comodato,
    sim_nao,
    soma,
    soma_relacionada,
)

CAMPOS_TOTAIS = ('valor_total_calc', 'valor_entrada_calc', 'repasse_logista', 'qtd_itens_calc', 'comodato', 'valor_produtos_calc')


def anotar_valores_da_venda(vendas: QuerySet) -> QuerySet:
    pagamentos = Pagamento.objects.all()
    qtd_parcelas = (
        Pagamento.objects.filter(venda=OuterRef('pk'), tipo_pagamento__parcelas=True)
        .order_by().values('venda').annotate(total=Sum('parcelas')).values('total')
    )
    qtd_itens = (
        ProdutoVenda.objects.filter(venda=OuterRef('pk'))
        .order_by().values('venda').annotate(total=Sum('quantidade')).values('total')
    )
    return vendas.annotate(
        valor_total_calc=soma_relacionada(pagamentos, 'venda', 'valor'),
        valor_entrada_calc=soma_relacionada(pagamentos.filter(tipo_pagamento__nome__iexact='ENTRADA'), 'venda', 'valor'),
        valor_contabilizado_calc=soma_relacionada(pagamentos.filter(tipo_pagamento__nao_contabilizar=False), 'venda', 'valor'),
        qtd_parcelas_calc=Coalesce(Subquery(qtd_parcelas, output_field=IntegerField()), Value(0)),
        qtd_itens_calc=Coalesce(Subquery(qtd_itens, output_field=IntegerField()), Value(0)),
        valor_produtos_calc=soma_relacionada(ProdutoVenda.objects.all(), 'venda', F('produto__valor') * F('quantidade')),
        bloqueada_calc=Exists(Pagamento.objects.filter(venda=OuterRef('pk'), bloqueado=True)),
    )


def financiado(comodato: bool, repasse, valor_produtos, entrada) -> Decimal:
    """Regra de `Venda.valor_financiado`: o repasse; no comodato (repasse 0), produtos − entrada."""
    if not comodato:
        return repasse or Decimal(0)
    return (valor_produtos or Decimal(0)) - (entrada or Decimal(0))


def _juros(total, entrada, valor_financiado, qtd_itens) -> Decimal:
    """Regra de `Venda.juros`: (total − (entrada + valor financiado)) × quantidade de itens."""
    return (total - (entrada + valor_financiado)) * qtd_itens


def juros(venda) -> Decimal:
    valor_financiado = financiado(venda.comodato, venda.repasse_logista, venda.valor_produtos_calc, venda.valor_entrada_calc)
    return _juros(venda.valor_total_calc, venda.valor_entrada_calc, valor_financiado, venda.qtd_itens_calc)


def _financiado_da_linha(linha: dict) -> Decimal:
    return financiado(linha['comodato'], linha['repasse_logista'], linha['valor_produtos_calc'], linha['valor_entrada_calc'])


def resumo_financeiro(vendas: QuerySet) -> dict:
    """Totais de valores das vendas, separando comodato (repasse 0, fica com a IPX) das demais.

    `demais_repasse` é o repasse ao lojista (só vendas comuns); `comodato_ipx` é o valor
    financiado das vendas de comodato, que fica todo com a IPX.
    """
    linhas = list(anotar_valores_da_venda(vendas).values(*CAMPOS_TOTAIS))
    comodato = [l for l in linhas if l['comodato']]
    return {
        'total_entrada': soma(l['valor_entrada_calc'] for l in linhas),
        'total_repasse': soma(l['repasse_logista'] for l in linhas),
        'total_valor': soma(l['valor_total_calc'] for l in linhas),
        'total_juros': soma(
            _juros(l['valor_total_calc'], l['valor_entrada_calc'], _financiado_da_linha(l), l['qtd_itens_calc'])
            for l in linhas
        ),
        **separar_comodato(linhas, lambda l: l['comodato'], lambda l: l['valor_total_calc']),
        'comodato_ipx': soma(_financiado_da_linha(l) for l in comodato),
        'demais_repasse': soma(l['repasse_logista'] for l in linhas if not l['comodato']),
    }


def consultar(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    vendas = Venda.objects.filter(is_deleted=False).filter(
        filtro_periodo('data_venda', filtros.get('data_inicial'), filtros.get('data_final'))
    )
    if filtros.get('vendedores'):
        vendas = vendas.filter(vendedor__in=filtros['vendedores'])
    if filtros.get('analise_serasa'):
        vendas = vendas.filter(cliente__comprovantes__restricao__in=[v == 'true' for v in filtros['analise_serasa']])
    if filtros.get('parcelas'):
        vendas = vendas.filter(analises_credito_venda__numero_parcelas__in=list(filtros['parcelas']))
    if filtros.get('produtos'):
        vendas = vendas.filter(produtos__in=filtros['produtos'])
    if filtros.get('analise_online') is not None:
        vendas = vendas.filter(analises_credito_venda__analise_online=filtros['analise_online'])
    vendas = filtrar_comodato(vendas, filtros, 'comodato')
    vendas = escopo.aplicar(vendas, 'loja')
    ids = vendas.values('pk').distinct()
    segunda_compra = PreAnaliseRapida.objects.filter(cliente_gerado_id=OuterRef('cliente_id'), segunda_compra=True)
    return (
        anotar_valores_da_venda(Venda.objects.filter(pk__in=ids))
        .annotate(is_segunda_compra=Exists(segunda_compra))
        .select_related('loja', 'vendedor', 'cliente__comprovantes', 'cliente__analise_credito')
        .prefetch_related(
            'produtos',
            Prefetch('analises_credito_venda', queryset=AnaliseCreditoCliente.objects.order_by('pk')),
        )
        .order_by('data_venda', 'pk')
    )


def totais(vendas: QuerySet, filtros: dict | None = None) -> dict:
    resumo = resumo_financeiro(Venda.objects.filter(pk__in=vendas.values('pk')))
    return {'total_vendas': resumo['comodato_quantidade'] + resumo['demais_quantidade'], **resumo}


def _analise_do_cliente(cliente):
    try:
        return cliente.analise_credito
    except AnaliseCreditoCliente.DoesNotExist:
        return None


def linha(venda) -> dict:
    analise = _analise_do_cliente(venda.cliente)
    da_venda = list(venda.analises_credito_venda.all())
    restricao = venda.cliente.comprovantes.restricao
    online = da_venda[0].analise_online if da_venda else None
    return {
        'id': venda.pk,
        'loja': venda.loja.nome if venda.loja else '',
        'cliente': venda.cliente.nome,
        'data_venda': venda.data_venda,
        'vendedor': str(venda.vendedor),
        'parcelas': venda.qtd_parcelas_calc,
        'produtos': [p.nome for p in venda.produtos.all()],
        'status_solicitacao': analise.status if analise else None,
        'status_solicitacao_rotulo': rotulo_status_analise(analise.status if analise else None),
        'segunda_compra': venda.is_segunda_compra,
        'restricao_serasa': restricao,
        'consulta_serasa': sim_nao(restricao, 'Positiva', 'Negativa'),
        'analise_online': online,
        'tipo': sim_nao(online, 'Online', 'Presencial'),
        'valor_entrada': venda.valor_entrada_calc,
        'valor_repasse': venda.repasse_logista,
        'valor_total': venda.valor_contabilizado_calc,
        'valor_juros': juros(venda),
        'pagamento_bloqueado': venda.bloqueada_calc,
        'comodato': venda.comodato,
    }


def linhas(vendas) -> list[dict]:
    return [linha(venda) for venda in vendas]
