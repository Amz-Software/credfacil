"""Indicadores do backoffice: contagem de solicitações e resumo da carteira da loja."""
import json
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from vendas.models import AnaliseCreditoCliente, Pagamento, Parcela, Venda

PERMISSAO_VER_TODAS_ANALISES = 'vendas.view_all_analise_credito'
PARCELAS_CONSIDERADAS_POR_VENDA = 3
TIPO_CREDFACIL = 'IPX'


def analises_visiveis(usuario, loja_id):
    """Todas as análises para quem tem `view_all_analise_credito`; senão só as da loja."""
    if usuario.has_perm(PERMISSAO_VER_TODAS_ANALISES):
        return AnaliseCreditoCliente.objects.all()
    return AnaliseCreditoCliente.objects.filter(loja_id=loja_id)


def contar_por_status(analises) -> dict[str, int]:
    """Total de análises por código de status, com zero para os status sem registro."""
    contagem = {
        item['status']: item['total']
        for item in analises.values('status').annotate(total=Count('id'))
    }
    return {
        **{codigo: 0 for codigo, _ in AnaliseCreditoCliente.STATUS_CHOICES},
        **contagem,
    }


def _primeiras_parcelas_por_venda(loja) -> dict[int, list]:
    """Até 3 parcelas IPX ativas (por vencimento) de cada venda da loja, numa só consulta."""
    parcelas = (
        Parcela.objects.filter(
            pagamento__venda__loja=loja,
            pagamento__tipo_pagamento__nome=TIPO_CREDFACIL,
            pagamento__desativado=False,
        )
        .order_by('pagamento__venda_id', 'data_vencimento', 'id')
        .values(
            'pagamento__venda_id', 'data_vencimento', 'valor', 'valor_pago',
            'pago', 'pagamento_efetuado', 'pagamento__devolucao',
        )
    )
    por_venda = defaultdict(list)
    for parcela in parcelas.iterator():
        lista = por_venda[parcela['pagamento__venda_id']]
        if len(lista) < PARCELAS_CONSIDERADAS_POR_VENDA:
            lista.append(parcela)
    return por_venda


def _valor_pago_efetivo(parcela: dict) -> Decimal:
    # Mesma regra de Parcela.valor_pago_efetivo.
    if parcela['valor_pago'] not in (None, 0):
        return parcela['valor_pago']
    return parcela['valor']


def _resumo_parcelas_ativas(loja, hoje) -> dict:
    qtd = defaultdict(int)
    valor = defaultdict(Decimal)
    total = 0
    for parcelas in _primeiras_parcelas_por_venda(loja).values():
        total += len(parcelas)
        for p in parcelas:
            em_aberto = not p['pago'] and not p['pagamento_efetuado'] and not p['pagamento__devolucao']
            if p['pago'] and not p['pagamento_efetuado']:
                qtd['pagas'] += 1
                valor['pagas'] += _valor_pago_efetivo(p)
            elif em_aberto and p['data_vencimento'] < hoje:
                qtd['vencidas'] += 1
                valor['vencidas'] += p['valor']
            elif em_aberto:
                qtd['a_vencer'] += 1
                valor['a_vencer'] += p['valor']
    return {
        'total_de_parcelas_geral': total,
        'parcelas_vencidas': qtd['vencidas'],
        'parcelas_pagas': qtd['pagas'],
        'parcelas_a_vencer': qtd['a_vencer'],
        'total_pagas': valor['pagas'],
        'total_vencidas': valor['vencidas'],
        'total_a_vencer': valor['a_vencer'],
        'total_geral_parcelas': valor['pagas'] + valor['vencidas'] + valor['a_vencer'],
    }


def _resumo_desativados(loja, hoje) -> dict:
    """Parcelas não pagas de pagamentos IPX desativados, separadas por vencimento."""
    parcelas = Parcela.objects.filter(
        pagamento__venda__loja=loja,
        pagamento__tipo_pagamento__nome=TIPO_CREDFACIL,
        pagamento__desativado=True,
        pago=False,
    ).values_list('data_vencimento', 'valor')
    resumo = {
        'total_desativados_vencidas': Decimal(0), 'qtd_desativados_vencidas': 0,
        'total_desativados_a_vencer': Decimal(0), 'qtd_desativados_a_vencer': 0,
    }
    for vencimento, valor in parcelas:
        chave = 'vencidas' if vencimento < hoje else 'a_vencer'
        resumo[f'total_desativados_{chave}'] += valor
        resumo[f'qtd_desativados_{chave}'] += 1
    resumo['total_pagamentos_desativados'] = Pagamento.objects.filter(
        venda__loja=loja, tipo_pagamento__nome=TIPO_CREDFACIL, desativado=True,
    ).count()
    return resumo


def _percentual(parte, total: float) -> float:
    return round(float(parte) / total * 100, 2) if total else 0


def _dados_grafico(ativas: dict, desativados: dict) -> str:
    desativado = desativados['total_desativados_vencidas'] + desativados['total_desativados_a_vencer']
    total = float(ativas['total_geral_parcelas']) + float(desativado)
    return json.dumps({
        'labels': ['Pagas', 'Vencidas', 'Desativados'],
        'data': [
            _percentual(ativas['total_pagas'], total),
            _percentual(ativas['total_vencidas'], total),
            _percentual(desativado, total),
        ],
    })


def resumo_carteira_loja(loja, hoje=None) -> dict:
    """KPIs da página inicial: vendas da loja e situação das 3 primeiras parcelas IPX.

    Parcelas de pagamentos em devolução contam só quando já pagas.
    """
    hoje = hoje or timezone.now().date()
    ativas = _resumo_parcelas_ativas(loja, hoje)
    desativados = _resumo_desativados(loja, hoje)
    return {
        'total_vendas_loja': Venda.objects.filter(loja=loja).count(),
        **ativas,
        **desativados,
        'dash': _dados_grafico(ativas, desativados),
    }
