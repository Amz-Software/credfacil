"""Relatório de situações: mesmo conteúdo de `FolhaRelatorioContasAReceberAvancadoView`.

Período pela data de criação da venda (só quando início e fim vêm juntos, como hoje);
situações combinadas com E; último contato do cliente com o analista que o registrou.
"""
from datetime import timedelta

from django.db.models import Prefetch, QuerySet

from vendas.models import Contato, Pagamento, ProdutoVenda

from .comum import EscopoRelatorio, filtrar_comodato, inicio_do_dia
from .contas_a_receber import contatos_do_cliente, primeiro_item

SITUACOES_FILTRAVEIS = (
    'lembrete', 'bo', 'flag_atrasado', 'sem_conexao', 'roubo', 'bloqueado', 'desativado', 'devolucao',
    'sem_contato', 'mais_prazo',
)
ROTULOS_SITUACAO = (
    ('bo', 'BO'), ('flag_atrasado', 'Cobrança'), ('sem_conexao', 'Desabilitado'), ('roubo', 'Roubo'),
    ('bloqueado', 'Bloqueado'), ('desativado', 'Desativado'), ('devolucao', 'Devolução'),
    ('sem_contato', 'Sem contato'), ('mais_prazo', 'Mais prazo'),
)


def consultar(filtros: dict, escopo: EscopoRelatorio) -> QuerySet:
    pagamentos = Pagamento.objects.exclude(venda__is_deleted=True).with_status_flags()
    pagamentos = escopo.aplicar(pagamentos, 'loja')
    pagamentos = filtrar_comodato(pagamentos, filtros, 'venda__comodato')
    inicio, fim = filtros.get('data_inicial'), filtros.get('data_final')
    if inicio and fim:
        pagamentos = pagamentos.filter(
            venda__criado_em__gte=inicio_do_dia(inicio), venda__criado_em__lt=inicio_do_dia(fim + timedelta(days=1)),
        )
    for situacao in filtros.get('situacoes') or []:
        if situacao in SITUACOES_FILTRAVEIS:
            pagamentos = pagamentos.filter(**{situacao: True})
    if filtros.get('status_pagamento'):
        pagamentos = pagamentos.filter(statuses__in=filtros['status_pagamento'])
    contatos = Contato.objects.select_related('criado_por').order_by('-criado_em', '-id')
    return (
        Pagamento.objects.filter(pk__in=pagamentos.values('pk'))
        .select_related('venda__loja', 'venda__cliente__informacao_pessoal', 'venda__cliente__contato_adicional')
        .prefetch_related(
            'statuses',
            Prefetch('venda__itens_venda', queryset=ProdutoVenda.objects.order_by('pk')),
            Prefetch('venda__cliente__contatos', queryset=contatos, to_attr='contatos_ordenados'),
        )
        .order_by('venda__criado_em', 'pk')
    )


def totais(pagamentos: QuerySet, filtros: dict | None = None) -> dict:
    """Sem valores na folha: só a quantidade, separando os pagamentos de vendas de comodato."""
    comodato = list(pagamentos.values_list('venda__comodato', flat=True))
    quantidade_comodato = sum(1 for valor in comodato if valor)
    return {
        'quantidade': len(comodato),
        'comodato_quantidade': quantidade_comodato,
        'demais_quantidade': len(comodato) - quantidade_comodato,
    }


def _linha(pagamento) -> dict:
    venda = pagamento.venda
    contatos = getattr(venda.cliente, 'contatos_ordenados', [])
    ultimo = contatos[0] if contatos else None
    autor = ultimo.criado_por if ultimo else None
    item = primeiro_item(venda)
    return {
        'pagamento_id': pagamento.pk,
        'loja': venda.loja.nome if venda.loja else '',
        'data_venda': venda.criado_em,
        'cliente': venda.cliente.nome,
        'lembrete': pagamento.lembrete,
        'comodato': venda.comodato,
        'contatos': contatos_do_cliente(venda.cliente),
        'imei': (item.imei if item else '') or '',
        'situacoes': [rotulo for campo, rotulo in ROTULOS_SITUACAO if getattr(pagamento, campo)],
        'status_pagamento': [s.nome for s in pagamento.statuses.all()],
        'analista_ultimo_registro': (autor.get_full_name() or autor.username) if autor else None,
        'ultimo_contato': (
            {'data': ultimo.criado_em, 'observacao': ultimo.observacao or ''} if ultimo else None
        ),
    }


def linhas(pagamentos) -> list[dict]:
    return [_linha(p) for p in pagamentos]
