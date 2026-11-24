"""Relatório de contas a receber: mesmo conteúdo de `FolhaRelatorioContasAReceberView` (financeiro/views.py).

Dois modos, como na folha atual:
- só o status "pago": uma linha por parcela paga no período (data do pagamento);
- demais casos: uma linha por pagamento, com filtro de status e de data por status.
Os valores por pagamento vêm de subconsultas que reproduzem os métodos de
`Pagamento` (`valor_atrasado`, `valor_pago_ultimo`, `valor_atual_a_vencer`,
`valor_a_vencer`, `valor_total_parcelas`, `parcelas_totais`, `valor_quitado`).
"""
from datetime import timedelta

from django.db.models import Count, DateField, IntegerField, OuterRef, Prefetch, Q, QuerySet, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from vendas.models import Pagamento, Parcela, ProdutoVenda

from .comum import (
    DINHEIRO,
    ZERO,
    EscopoRelatorio,
    filtrar_comodato,
    separar_comodato,
    soma,
    soma_relacionada,
    valor_pago_efetivo,
    valor_restante,
)

MODO_PARCELAS = 'parcelas'
MODO_PAGAMENTOS = 'pagamentos'


def modo(filtros: dict) -> str:
    status = set(filtros.get('status') or [])
    return MODO_PARCELAS if status == {'pago'} else MODO_PAGAMENTOS


# ── Modo parcelas pagas ─────────────────────────────────────────────────────

def _consultar_parcelas_pagas(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    fim = filtros['data_final'] + timedelta(days=1)
    parcelas = Parcela.objects.filter(pago=True, data_pagamento__gte=filtros['data_inicial'], data_pagamento__lt=fim)
    parcelas = filtrar_comodato(parcelas, filtros, 'pagamento__venda__comodato')
    return (
        escopo.aplicar(parcelas, 'pagamento__loja')
        .annotate(valor_pago_calc=valor_pago_efetivo())
        .select_related(
            'pagamento__venda__loja', 'pagamento__venda__cliente__informacao_pessoal',
            'pagamento__venda__cliente__contato_adicional',
        )
        .prefetch_related(_itens('pagamento__venda__itens_venda'))
        .order_by('data_pagamento', 'pagamento_id', 'numero_parcela', 'pk')
    )


# ── Modo pagamentos ─────────────────────────────────────────────────────────

def _primeira_data(parcelas: QuerySet, ordem: str) -> Subquery:
    return Subquery(parcelas.filter(pagamento=OuterRef('pk')).order_by(ordem).values(ordem.lstrip('-'))[:1], output_field=DateField())


def anotar_valores_do_pagamento(pagamentos: QuerySet) -> QuerySet:
    hoje = timezone.localdate()
    parcelas = Parcela.objects.all()
    em_aberto = parcelas.filter(pago=False)
    pagas = parcelas.filter(pago=True)
    restante = valor_restante()
    proxima_restante = Subquery(
        em_aberto.filter(pagamento=OuterRef('pk'), data_vencimento__gte=hoje)
        .order_by('data_vencimento').annotate(r=restante).values('r')[:1],
        output_field=DINHEIRO,
    )
    ultima_paga = Subquery(
        pagas.filter(pagamento=OuterRef('pk')).order_by('-data_pagamento')
        .annotate(v=valor_pago_efetivo()).values('v')[:1],
        output_field=DINHEIRO,
    )
    total_parcelas = Subquery(
        parcelas.filter(pagamento=OuterRef('pk')).order_by().values('pagamento')
        .annotate(n=Count('pk')).values('n'),
        output_field=IntegerField(),
    )
    return pagamentos.annotate(
        valor_atrasado_calc=soma_relacionada(em_aberto.filter(data_vencimento__lt=hoje), 'pagamento', restante),
        valor_a_vencer_calc=soma_relacionada(em_aberto.filter(data_vencimento__gte=hoje), 'pagamento', restante),
        valor_atual_a_vencer_calc=Coalesce(proxima_restante, ZERO),
        valor_pago_ultimo_calc=Coalesce(ultima_paga, ZERO),
        valor_total_parcelas_calc=soma_relacionada(parcelas, 'pagamento', 'valor'),
        parcelas_totais_calc=Coalesce(total_parcelas, Value(0)),
        valor_quitado_calc=soma_relacionada(pagas, 'pagamento', valor_pago_efetivo()),
        proximo_vencimento=_primeira_data(em_aberto.filter(data_vencimento__gte=hoje), 'data_vencimento'),
        ultimo_vencimento=_primeira_data(em_aberto.filter(data_vencimento__lt=hoje), 'data_vencimento'),
        ultimo_pagamento=_primeira_data(pagas, 'data_pagamento'),
    )


def _filtro_status(status_lista: list, inicio, fim_mais_um) -> tuple[Q | None, Q]:
    """Mesma montagem de `FolhaRelatorioContasAReceberView`: OR dos status e OR das datas."""
    def entre(campo):
        return Q(**{f'{campo}__isnull': False, f'{campo}__gte': inicio, f'{campo}__lt': fim_mais_um})

    por_status = {
        'pendente': (Q(com_pagamento_pendente=True), entre('proximo_vencimento')),
        'pago': (Q(), entre('ultimo_pagamento')),
        'atrasado': (Q(com_parcela_atrasada=True), entre('ultimo_vencimento')),
        'quitado': (Q(todas_parcelas_pagas=True), Q()),
    }
    for flag in ('desativado', 'bloqueado', 'sem_contato', 'mais_prazo', 'lembrete', 'flag_atrasado',
                 'sem_conexao', 'roubo', 'devolucao'):
        por_status[flag] = (Q(**{flag: True}), Q())
    q_status, datas = None, Q()
    for status in status_lista:
        if status not in por_status:
            continue
        q, data_q = por_status[status]
        q_status = q if q_status is None else q_status | q
        datas = datas | data_q
    return q_status, datas


def _consultar_pagamentos(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    inicio, fim_mais_um = filtros['data_inicial'], filtros['data_final'] + timedelta(days=1)
    status_lista = list(filtros.get('status') or [])
    pagamentos = anotar_valores_do_pagamento(
        Pagamento.objects.filter(venda__is_deleted=False, devolucao=False).with_status_flags()
    )
    pagamentos = escopo.aplicar(pagamentos, 'loja')
    pagamentos = filtrar_comodato(pagamentos, filtros, 'venda__comodato')
    if filtros.get('status_pagamento'):
        pagamentos = pagamentos.filter(statuses__in=filtros['status_pagamento'])
    if status_lista and 'todos' not in status_lista:
        q_status, datas = _filtro_status(status_lista, inicio, fim_mais_um)
        if q_status is not None:
            pagamentos = pagamentos.filter(q_status)
        if datas:
            pagamentos = pagamentos.filter(datas)
    else:
        def entre(campo):
            return Q(**{f'{campo}__isnull': False, f'{campo}__gte': inicio, f'{campo}__lt': fim_mais_um})
        pagamentos = pagamentos.filter(
            entre('proximo_vencimento') | entre('ultimo_vencimento') | entre('ultimo_pagamento') | Q(sem_conexao=True)
        )
    ids = pagamentos.values('pk')
    return (
        anotar_valores_do_pagamento(Pagamento.objects.filter(pk__in=ids).with_status_flags())
        .select_related(
            'venda__loja', 'venda__cliente__informacao_pessoal', 'venda__cliente__contato_adicional',
        )
        .prefetch_related('statuses', _itens('venda__itens_venda'))
        .order_by('venda__data_venda', 'pk')
    )


def _itens(caminho: str) -> Prefetch:
    return Prefetch(caminho, queryset=ProdutoVenda.objects.select_related('produto').order_by('pk'))


def consultar(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    if modo(filtros) == MODO_PARCELAS:
        return _consultar_parcelas_pagas(filtros, escopo)
    return _consultar_pagamentos(filtros, escopo)


def totais(consulta: QuerySet, filtros: dict) -> dict:
    """Valor de referência de comodato/demais: o valor pago (modo parcelas) ou o total das parcelas."""
    if modo(filtros) == MODO_PARCELAS:
        linhas = list(consulta.values('valor_pago_calc', 'pagamento__venda__comodato'))
        return {
            'modo': MODO_PARCELAS, 'quantidade': len(linhas), 'total_pago': soma(l['valor_pago_calc'] for l in linhas),
            'total_atrasado': 0, 'total_a_vencer': 0, 'total_proximo_vencimento': 0, 'total': 0, 'total_quitado': 0,
            **separar_comodato(linhas, lambda l: bool(l['pagamento__venda__comodato']), lambda l: l['valor_pago_calc']),
        }
    linhas = list(consulta.values(
        'valor_atrasado_calc', 'valor_pago_ultimo_calc', 'valor_a_vencer_calc', 'valor_atual_a_vencer_calc',
        'valor_total_parcelas_calc', 'valor_quitado_calc', 'venda__comodato',
    ))
    return {
        'modo': MODO_PAGAMENTOS,
        'quantidade': len(linhas),
        'total_atrasado': soma(l['valor_atrasado_calc'] for l in linhas),
        'total_pago': soma(l['valor_pago_ultimo_calc'] for l in linhas),
        'total_a_vencer': soma(l['valor_a_vencer_calc'] for l in linhas),
        'total_proximo_vencimento': soma(l['valor_atual_a_vencer_calc'] for l in linhas),
        'total': soma(l['valor_total_parcelas_calc'] for l in linhas),
        'total_quitado': soma(l['valor_quitado_calc'] for l in linhas),
        **separar_comodato(linhas, lambda l: bool(l['venda__comodato']), lambda l: l['valor_total_parcelas_calc']),
    }


# ── Linhas ──────────────────────────────────────────────────────────────────

def contatos_do_cliente(cliente) -> list[str]:
    """Telefones e contatos de referência, na ordem da folha atual."""
    contatos = [cliente.telefone, cliente.telefone_secundario]
    for relacao in ('informacao_pessoal', 'contato_adicional'):
        relacionado = getattr(cliente, relacao, None)
        contatos.append(relacionado.contato if relacionado else None)
    return [c for c in contatos if c]


def primeiro_item(venda):
    itens = list(venda.itens_venda.all())
    return itens[0] if itens else None


SITUACOES_CONTA = (
    ('desativado', 'DESATIVADO'), ('bloqueado', 'BLOQUEADO'), ('sem_conexao', 'DESABILITADO'),
    ('sem_contato', 'SEM CONTATO'), ('mais_prazo', 'MAIS PRAZO'), ('com_parcela_atrasada', 'ATRASADO'),
    ('com_pagamento_pendente', 'A VENCER'), ('pago_dentro_prazo', 'PAGO'), ('todas_parcelas_pagas', 'QUITADO'),
    ('flag_atrasado', 'COBRANÇA'),
)


def situacoes(pagamento) -> list[str]:
    rotulos = [rotulo for campo, rotulo in SITUACOES_CONTA if getattr(pagamento, campo, False)]
    return rotulos or ['ATIVO']


def _base(venda, pagamento) -> dict:
    item = primeiro_item(venda)
    return {
        'pagamento_id': pagamento.pk,
        'loja': venda.loja.nome if venda.loja else '',
        'data_venda': venda.data_venda,
        'cliente': venda.cliente.nome,
        'produto': item.produto.nome if item else '',
        'imei': (item.imei if item else '') or '',
        'contatos': contatos_do_cliente(venda.cliente),
        'comodato': venda.comodato,
    }


def _linha_parcela(parcela) -> dict:
    return {
        **_base(parcela.pagamento.venda, parcela.pagamento),
        'parcela_id': parcela.pk,
        'situacoes': ['PAGO'],
        'valor_atrasado': None, 'primeiro_vencimento': None,
        'valor_pago': parcela.valor_pago_calc, 'ultimo_pagamento': parcela.data_pagamento,
        'proxima_parcela': None, 'valor_a_vencer': None, 'proximo_vencimento': None,
        'valor_total': None, 'parcelas_totais': None, 'parcelas_pagas': None, 'valor_quitado': None,
    }


def _linha_pagamento(pagamento) -> dict:
    return {
        **_base(pagamento.venda, pagamento),
        'parcela_id': None,
        'situacoes': situacoes(pagamento),
        'valor_atrasado': pagamento.valor_atrasado_calc,
        'primeiro_vencimento': pagamento.ultimo_vencimento,
        'valor_pago': pagamento.valor_pago_ultimo_calc,
        'ultimo_pagamento': pagamento.ultimo_pagamento,
        'proxima_parcela': pagamento.valor_atual_a_vencer_calc,
        'valor_a_vencer': pagamento.valor_a_vencer_calc,
        'proximo_vencimento': pagamento.proximo_vencimento,
        'valor_total': pagamento.valor_total_parcelas_calc,
        'parcelas_totais': pagamento.parcelas_totais_calc,
        'parcelas_pagas': pagamento.parcelas_pagas,
        'valor_quitado': pagamento.valor_quitado_calc,
    }


def linhas(itens) -> list[dict]:
    return [_linha_parcela(i) if isinstance(i, Parcela) else _linha_pagamento(i) for i in itens]
