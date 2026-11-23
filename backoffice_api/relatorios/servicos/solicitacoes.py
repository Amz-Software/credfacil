"""Relatório de solicitações: mesmo conteúdo de `FolhaRelatorioSolicitacoesView`.

Como na folha atual: cada linha mostra os valores da venda vinculada à análise;
os totais somam todas as vendas de cada cliente (`cliente.vendas`).
"""
from django.db.models import QuerySet

from vendas.models import AnaliseCreditoCliente, Cliente, Venda

from .comum import EscopoRelatorio, filtro_periodo, rotulo_status_analise, sim_nao, soma
from .vendas import anotar_valores_da_venda, juros


def consultar(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    clientes = Cliente.objects.filter(filtro_periodo('criado_em', filtros.get('data_inicial'), filtros.get('data_final')))
    if filtros.get('status_solicitacao'):
        clientes = clientes.filter(analise_credito__status__in=list(filtros['status_solicitacao']))
    if filtros.get('parcelas'):
        clientes = clientes.filter(analise_credito__numero_parcelas__in=list(filtros['parcelas']))
    if filtros.get('analise_serasa'):
        clientes = clientes.filter(comprovantes__restricao__in=[v == 'true' for v in filtros['analise_serasa']])
    if filtros.get('venda_realizada') is not None:
        clientes = clientes.filter(analise_credito__venda__isnull=not filtros['venda_realizada'])
    if filtros.get('analise_online') is not None:
        clientes = clientes.filter(analise_credito__analise_online=filtros['analise_online'])
    if filtros.get('vendedores'):
        clientes = clientes.filter(analise_credito__criado_por__in=filtros['vendedores'])
    if filtros.get('produtos'):
        clientes = clientes.filter(analise_credito__produto__in=filtros['produtos'])
    clientes = escopo.aplicar(clientes, 'loja')
    return (
        Cliente.objects.filter(pk__in=clientes.values('pk'))
        .select_related('loja', 'comprovantes', 'analise_credito__criado_por', 'analise_credito__produto')
        .order_by('criado_em', 'pk')
    )


def totais(clientes: QuerySet, filtros: dict | None = None) -> dict:
    vendas = list(
        anotar_valores_da_venda(Venda.objects.filter(cliente__in=clientes.values('pk')))
        .values('valor_total_calc', 'valor_entrada_calc', 'repasse_logista', 'qtd_itens_calc')
    )
    return {
        'total_solicitacoes': clientes.count(),
        'total_entrada': soma(v['valor_entrada_calc'] for v in vendas),
        'total_repasse': soma(v['repasse_logista'] for v in vendas),
        'total_valor': soma(v['valor_total_calc'] for v in vendas),
        'total_juros': soma(
            (v['valor_total_calc'] - (v['valor_entrada_calc'] + (v['repasse_logista'] or 0))) * v['qtd_itens_calc']
            for v in vendas
        ),
    }


def _analise(cliente):
    try:
        return cliente.analise_credito
    except AnaliseCreditoCliente.DoesNotExist:
        return None


def linhas(clientes) -> list[dict]:
    clientes = list(clientes)
    analises = [a for a in (_analise(c) for c in clientes) if a]
    vendas = {
        v.pk: v for v in anotar_valores_da_venda(Venda.objects.filter(pk__in=[a.venda_id for a in analises if a.venda_id]))
    }
    return [_linha(cliente, _analise(cliente), vendas) for cliente in clientes]


def _linha(cliente, analise, vendas: dict) -> dict:
    venda = vendas.get(analise.venda_id) if analise and analise.venda_id else None
    restricao = cliente.comprovantes.restricao
    online = analise.analise_online if analise else None
    criador = analise.criado_por if analise else None
    return {
        'id': cliente.pk,
        'cliente': cliente.nome or '',
        'analise_id': analise.pk if analise else None,
        'loja': cliente.loja.nome if cliente.loja else '',
        'data_solicitacao': cliente.criado_em,
        'vendedor': (criador.get_full_name() if criador else '') or '',
        'status_solicitacao': analise.status if analise else None,
        'status_solicitacao_rotulo': rotulo_status_analise(analise.status if analise else None),
        'parcelas': analise.numero_parcelas if analise else None,
        'produto': analise.produto.nome if analise else '',
        'restricao_serasa': restricao,
        'consulta_serasa': sim_nao(restricao, 'Positiva', 'Negativa'),
        'analise_online': online,
        'tipo': sim_nao(online, 'Online', 'Presencial'),
        'venda_gerada': venda is not None,
        'valor_entrada': venda.valor_entrada_calc if venda else 0,
        'valor_repasse': venda.repasse_logista if venda else 0,
        'valor_total': venda.valor_contabilizado_calc if venda else 0,
        'valor_juros': juros(venda) if venda else 0,
    }
