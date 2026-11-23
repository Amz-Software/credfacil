"""Relatório de vendas: mesmo conteúdo de `FolhaRelatorioVendasView` (vendas/views/relatorios.py).

Os valores por venda vêm de subconsultas que reproduzem as propriedades do modelo
`Venda` (`valor_total_venda`, `valor_entrada_cliente`, `pagamentos_valor_total`,
`qtd_total_parcelas`, `juros`), para não consultar o banco venda a venda.
Os testes conferem que os números batem com as propriedades do modelo.
"""
from decimal import Decimal

from django.db.models import Exists, IntegerField, OuterRef, Prefetch, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from vendas.models import AnaliseCreditoCliente, Pagamento, PreAnaliseRapida, ProdutoVenda, Venda

from .comum import EscopoRelatorio, filtro_periodo, rotulo_status_analise, sim_nao, soma, soma_relacionada


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
        bloqueada_calc=Exists(Pagamento.objects.filter(venda=OuterRef('pk'), bloqueado=True)),
    )


def juros(venda) -> Decimal:
    """Regra de `Venda.juros`: (total − (entrada + repasse)) × quantidade de itens."""
    return (venda.valor_total_calc - (venda.valor_entrada_calc + (venda.repasse_logista or 0))) * venda.qtd_itens_calc


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
    linhas = list(vendas.values('valor_total_calc', 'valor_entrada_calc', 'repasse_logista', 'qtd_itens_calc'))
    return {
        'total_vendas': len(linhas),
        'total_entrada': soma(l['valor_entrada_calc'] for l in linhas),
        'total_repasse': soma(l['repasse_logista'] for l in linhas),
        'total_valor': soma(l['valor_total_calc'] for l in linhas),
        'total_juros': soma(
            (l['valor_total_calc'] - (l['valor_entrada_calc'] + (l['repasse_logista'] or 0))) * l['qtd_itens_calc']
            for l in linhas
        ),
    }


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
    }


def linhas(vendas) -> list[dict]:
    return [linha(venda) for venda in vendas]
