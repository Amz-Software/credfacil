"""Constantes de contas a receber: situações de cobrança, estados e filtros."""

# Situações de cobrança: campo booleano de `Pagamento` -> rótulo da tela de detalhe.
# A ordem é a mesma da tela Django (contas_a_receber_detail.html).
SITUACOES = (
    ('lembrete', 'Lembrete'),
    ('bo', 'BO'),
    ('flag_atrasado', 'Cobrança'),
    ('sem_conexao', 'Desabilitado'),
    ('roubo', 'Roubo'),
    ('sem_contato', 'Sem contato'),
    ('mais_prazo', 'Mais prazo'),
    ('bloqueado', 'Bloquear aparelho'),
    ('desativado', 'Desativar cliente'),
    ('devolucao', 'Devolução'),
)
CHAVES_SITUACAO = tuple(chave for chave, _ in SITUACOES)
ROTULOS_SITUACAO = dict(SITUACOES)

# Filtro da lista por parcela com pagamento informado pelo cliente.
FILTRO_PAGAMENTO_EFETUADO = 'pagamento_efetuado'
FILTROS_SITUACAO = CHAVES_SITUACAO + (FILTRO_PAGAMENTO_EFETUADO,)

# Filtro `status` da lista (mesmos valores da tela Django).
STATUS_NO_PRAZO = 'no_prazo'
STATUS_ATRASADO = 'atrasado'
STATUS_QUITADO = 'quitado'
STATUS_PENDENTE = 'pendente'
STATUS_LISTA = (STATUS_NO_PRAZO, STATUS_ATRASADO, STATUS_QUITADO, STATUS_PENDENTE)

# Estado exibido na lista e no detalhe (primeira condição verdadeira vence).
ROTULOS_ESTADO = {
    'desativado': 'Desativado',
    'devolucao': 'Devolução',
    'bloqueado': 'Bloqueado',
    'sem_contato': 'Sem contato',
    'mais_prazo': 'Mais prazo',
    'atrasado': 'Atrasado',
    'pendente': 'A vencer',
    'pago': 'Pago',
    'quitado': 'Quitado',
    'sem_situacao': '—',
}

# Situação da primeira parcela em aberto (verificar_atraso_parcela da tela Django).
PARCELA_EM_DIA = 'em_dia'
PARCELA_ATRASADA = 'atrasado'
PARCELA_PAGA_PARCIALMENTE = 'pago_parcialmente'

# Ordenação da lista: valor de `?ordenar=` -> campo do queryset.
ORDENACAO_PROXIMO_VENCIMENTO = 'proximo_vencimento'
ORDENACAO_LISTA = {
    'criado_em': 'criado_em',
    'id': 'id',
    'valor': 'valor',
    'cliente': 'venda__cliente__nome',
    ORDENACAO_PROXIMO_VENCIMENTO: 'next_vencimento',  # anotado em `filtros.ordenar`
}
ORDENACAO_PADRAO = '-criado_em'

MAXIMO_PARCELAS_EXTRAS = 4
MINIMO_CARACTERES_MOTIVO = 5
DESCONTO_MAXIMO = 100

GRUPOS_ANALISTA_ADMIN = ('ANALISTA', 'ADMINISTRADOR')
PERMISSAO_GLOBAL_PAGAMENTOS = 'vendas.can_view_all_payments'
PERMISSAO_FILTRO_LOJA = 'vendas.can_view_all_stores'
