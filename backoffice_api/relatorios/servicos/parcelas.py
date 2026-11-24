"""Relatório de parcelas (grade por status): mesmos filtros de `_FiltroParcelasMixin` (financeiro/views.py).

Cada linha é um pagamento parcelado com a grade das parcelas (paga, atrasada ou a
vencer) e os totais da linha, calculados como na planilha atual.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from vendas.models import Pagamento, Parcela, ProdutoVenda

from .comum import EscopoRelatorio, filtrar_comodato, separar_comodato, soma

PAGO, ATRASADO, A_VENCER = 'pago', 'atrasado', 'a_vencer'


def consultar(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    pagamentos = (
        Pagamento.objects.exclude(venda__is_deleted=True)
        .filter(tipo_pagamento__parcelas=True)
        .exclude(tipo_pagamento__caixa=True)
        .with_status_flags()
    )
    pagamentos = escopo.aplicar(pagamentos, 'loja')
    pagamentos = filtrar_comodato(pagamentos, filtros, 'venda__comodato')
    status = filtros.get('status') or 'todos'
    if status == 'atrasado':
        pagamentos = pagamentos.filter(com_parcela_atrasada=True)
    elif status == 'a_vencer':
        pagamentos = pagamentos.filter(com_pagamento_pendente=True)
    elif status == 'quitado':
        pagamentos = pagamentos.filter(todas_parcelas_pagas=True)
    if filtros.get('data_inicial'):
        pagamentos = pagamentos.filter(parcelas_pagamento__data_vencimento__gte=filtros['data_inicial'])
    if filtros.get('data_final'):
        pagamentos = pagamentos.filter(parcelas_pagamento__data_vencimento__lte=filtros['data_final'])
    busca = (filtros.get('busca') or '').strip()
    if busca:
        pagamentos = pagamentos.filter(Q(venda__cliente__nome__icontains=busca) | Q(venda__cliente__cpf__icontains=busca))
    return (
        Pagamento.objects.filter(pk__in=pagamentos.values('pk'))
        .select_related('venda__cliente', 'venda__loja', 'loja')
        .prefetch_related(
            Prefetch('parcelas_pagamento', queryset=Parcela.objects.order_by('numero_parcela', 'pk')),
            Prefetch('venda__itens_venda', queryset=ProdutoVenda.objects.select_related('produto').order_by('pk')),
        )
        .order_by('venda__loja__nome', 'venda__cliente__nome', 'pk')
    )


def situacao_parcela(parcela: Parcela, hoje: date) -> str:
    if parcela.pago:
        return PAGO
    if parcela.data_vencimento and parcela.data_vencimento < hoje:
        return ATRASADO
    return A_VENCER


def linha(pagamento: Pagamento, hoje: date | None = None) -> dict:
    hoje = hoje or timezone.localdate()
    venda = pagamento.venda
    totais = {'total': Decimal(0), PAGO: Decimal(0), ATRASADO: Decimal(0), A_VENCER: Decimal(0)}
    grade = []
    for parcela in pagamento.parcelas_pagamento.all():
        situacao = situacao_parcela(parcela, hoje)
        totais['total'] += parcela.valor or Decimal(0)
        totais[situacao] += parcela.valor_pago_efetivo if situacao == PAGO else parcela.valor_restante
        grade.append({
            'numero': parcela.numero_parcela, 'valor': parcela.valor,
            'vencimento': parcela.data_vencimento, 'situacao': situacao,
        })
    loja = venda.loja if venda and venda.loja else pagamento.loja
    aparelhos = ', '.join(i.produto.nome for i in venda.itens_venda.all() if i.produto_id) if venda else ''
    return {
        'pagamento_id': pagamento.pk,
        'loja': loja.nome if loja else '',
        'cliente': venda.cliente.nome if venda and venda.cliente_id else '—',
        'aparelho': aparelhos or '—',
        'comodato': bool(venda and venda.comodato),
        'parcelas': grade,
        'total': totais['total'],
        'total_pago': totais[PAGO],
        'total_atrasado': totais[ATRASADO],
        'total_a_vencer': totais[A_VENCER],
    }


def linhas(pagamentos) -> list[dict]:
    hoje = timezone.localdate()
    return [linha(p, hoje) for p in pagamentos]


def totais(pagamentos: QuerySet, filtros: dict | None = None) -> dict:
    todas = linhas(pagamentos)
    return {
        'quantidade': len(todas),
        'maximo_parcelas': max((len(l['parcelas']) for l in todas), default=0),
        'total': soma(l['total'] for l in todas),
        'total_pago': soma(l['total_pago'] for l in todas),
        'total_atrasado': soma(l['total_atrasado'] for l in todas),
        'total_a_vencer': soma(l['total_a_vencer'] for l in todas),
        **separar_comodato(todas, lambda l: l['comodato'], lambda l: l['total']),
    }
