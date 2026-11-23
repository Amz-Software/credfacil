"""Consultas de vendas da API do backoffice: querysets anotados, filtros e ordenação.

As views só combinam estas funções com o escopo de lojas (`filtrar_por_lojas`).
"""
import re
from datetime import date
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from estoque.models import EstoqueImei
from vendas.models import AnaliseCreditoCliente, Pagamento, Parcela, ProdutoVenda, Venda

VERDADEIROS = ('1', 'true', 'sim', 'on')
FALSOS = ('0', 'false', 'nao', 'não', 'off')
TODAS = 'todas'
ORIGEM_MANUAL = 'manual'
ORIGEM_ANALISE = 'analise'
MINIMO_DIGITOS_CPF = 3
MINIMO_DIGITOS_IMEI = 4
MAXIMO_DIGITOS_NUMERO = 9

_DECIMAL = DecimalField(max_digits=12, decimal_places=2)

ORDENACAO_VENDAS = {
    'numero': 'id',
    'data_venda': 'data_venda',
    'cliente': 'cliente__nome',
    'loja': 'loja__nome',
    'vendedor': 'vendedor__first_name',
    'total': 'total',
    'modificado_em': 'modificado_em',
}
ORDENACAO_PRODUTOS_VENDIDOS = {
    'data_venda': 'venda__data_venda',
    'produto': 'produto__nome',
    'cliente': 'venda__cliente__nome',
    'loja': 'venda__loja__nome',
    'valor': 'valor_unitario',
    'venda': 'venda_id',
}


# --- leitura de parâmetros --------------------------------------------------------

def somente_digitos(valor: str | None) -> str:
    return re.sub(r'\D', '', valor or '')


def ler_booleano(params, campo: str) -> bool | None:
    """True/False pelo texto do parâmetro; None quando ausente. Valor estranho → 400."""
    valor = (params.get(campo) or '').strip().lower()
    if not valor:
        return None
    if valor in VERDADEIROS:
        return True
    if valor in FALSOS:
        return False
    raise ValidationError({campo: ['Use true ou false.']})


def ler_inteiro(params, campo: str) -> int | None:
    valor = (params.get(campo) or '').strip()
    if not valor:
        return None
    if not valor.isdigit() or len(valor) > MAXIMO_DIGITOS_NUMERO:
        raise ValidationError({campo: ['Informe um número válido.']})
    return int(valor)


def ler_data(params, campo: str) -> date | None:
    valor = (params.get(campo) or '').strip()
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ValidationError({campo: ['Data inválida. Use o formato AAAA-MM-DD.']})


def filtrar_periodo(queryset: QuerySet, params, campo_data: str) -> QuerySet:
    inicio, fim = ler_data(params, 'data_inicio'), ler_data(params, 'data_fim')
    if inicio and fim and inicio > fim:
        raise ValidationError({'data_fim': ['A data final deve ser igual ou posterior à inicial.']})
    if inicio:
        queryset = queryset.filter(**{f'{campo_data}__date__gte': inicio})
    if fim:
        queryset = queryset.filter(**{f'{campo_data}__date__lte': fim})
    return queryset


def ordenar(queryset: QuerySet, valor: str | None, mapa: dict[str, str], padrao: str) -> QuerySet:
    """Ordena por `?ordenar=campo` ou `-campo`, só com os campos da lista branca."""
    valor = (valor or '').strip() or padrao
    descendente = valor.startswith('-')
    campo = mapa.get(valor.lstrip('-'))
    if campo is None:
        permitidos = ', '.join(sorted(mapa))
        raise ValidationError({'ordenar': [f'Ordenação inválida. Use um destes campos: {permitidos}.']})
    return queryset.order_by(f'-{campo}' if descendente else campo, '-pk')


# --- vendas -------------------------------------------------------------------------

def _total_dos_itens() -> Coalesce:
    valor_item = ExpressionWrapper(
        F('valor_unitario') * F('quantidade') - F('valor_desconto'), output_field=_DECIMAL,
    )
    soma = (
        ProdutoVenda.objects.filter(venda=OuterRef('pk'))
        .values('venda')
        .annotate(soma=Sum(valor_item))
        .values('soma')
    )
    return Coalesce(Subquery(soma, output_field=_DECIMAL), Value(Decimal('0')), output_field=_DECIMAL)


def vendas_anotadas() -> QuerySet:
    """Vendas com total dos itens, origem (análise) e presença de iPhone, sem N+1."""
    return Venda.objects.select_related('cliente', 'loja', 'vendedor', 'modificado_por').annotate(
        total=_total_dos_itens(),
        veio_de_analise=Exists(AnaliseCreditoCliente.objects.filter(venda=OuterRef('pk'))),
        possui_iphone=Exists(
            ProdutoVenda.objects.filter(venda=OuterRef('pk'), produto__is_iphone=True)
        ),
    )


def com_detalhes(queryset: QuerySet) -> QuerySet:
    """Acrescenta itens, pagamentos com parcelas e a análise de origem (prefetch)."""
    parcelas = Parcela.objects.order_by('numero_parcela', 'pk')
    pagamentos = (
        Pagamento.objects.select_related('tipo_pagamento')
        .prefetch_related(Prefetch('parcelas_pagamento', queryset=parcelas))
        .order_by('pk')
    )
    return queryset.select_related('criado_por', 'caixa').prefetch_related(
        Prefetch('itens_venda', queryset=ProdutoVenda.objects.select_related('produto').order_by('pk')),
        Prefetch('pagamentos', queryset=pagamentos),
        Prefetch(
            'analises_credito_venda',
            queryset=AnaliseCreditoCliente.objects.select_related('produto', 'aprovado_por'),
        ),
    )


def q_busca_venda(termo: str) -> Q:
    """Número da venda, nome ou CPF do cliente, ou IMEI de um item."""
    termo = termo.strip()
    digitos = somente_digitos(termo)
    filtro = Q(cliente__nome__icontains=termo)
    if digitos and digitos == termo and len(digitos) <= MAXIMO_DIGITOS_NUMERO:
        filtro |= Q(pk=int(digitos))
    if len(digitos) >= MINIMO_DIGITOS_CPF:
        filtro |= Q(cliente__cpf__contains=digitos)
    if len(digitos) >= MINIMO_DIGITOS_IMEI:
        filtro |= Q(pk__in=ProdutoVenda.objects.filter(imei__icontains=digitos).values('venda_id'))
    return filtro


def _filtrar_situacao(queryset: QuerySet, params) -> QuerySet:
    canceladas = (params.get('canceladas') or '').strip().lower()
    if canceladas != TODAS:
        queryset = queryset.filter(is_deleted=bool(ler_booleano(params, 'canceladas')))
    trocadas = ler_booleano(params, 'trocadas')
    if trocadas is not None:
        queryset = queryset.filter(is_trocado=trocadas)
    return queryset


def filtrar_vendas(queryset: QuerySet, params, *, pode_filtrar_loja: bool) -> QuerySet:
    """Filtros da lista de vendas. `?loja=` só vale para quem vê todas as lojas."""
    busca = (params.get('busca') or '').strip()
    if busca:
        queryset = queryset.filter(q_busca_venda(busca))
    cliente = (params.get('cliente') or '').strip()
    if cliente:
        queryset = queryset.filter(cliente__nome__icontains=cliente)
    numero = ler_inteiro(params, 'numero')
    if numero is not None:
        queryset = queryset.filter(pk=numero)
    loja = ler_inteiro(params, 'loja')
    if loja is not None and pode_filtrar_loja:
        queryset = queryset.filter(loja_id=loja)
    origem = (params.get('origem') or '').strip().lower()
    if origem not in ('', ORIGEM_MANUAL, ORIGEM_ANALISE):
        raise ValidationError({'origem': ['Use manual ou analise.']})
    if origem:
        queryset = queryset.filter(veio_de_analise=(origem == ORIGEM_ANALISE))
    queryset = _filtrar_situacao(queryset, params)
    return filtrar_periodo(queryset, params, 'data_venda')


def buscar_vendas(queryset: QuerySet, termo: str, limite: int) -> QuerySet:
    """Busca global: número exato primeiro, depois as mais recentes."""
    filtro = q_busca_venda(termo)
    digitos = somente_digitos(termo)
    exato = int(digitos) if digitos and digitos == termo.strip() and len(digitos) <= MAXIMO_DIGITOS_NUMERO else 0
    prioridade = Case(When(pk=exato, then=Value(0)), default=Value(1), output_field=IntegerField())
    return queryset.filter(filtro).annotate(prioridade=prioridade).order_by('prioridade', '-data_venda', '-pk')[:limite]


# --- produtos vendidos -----------------------------------------------------------

def produtos_vendidos() -> QuerySet:
    return ProdutoVenda.objects.select_related(
        'produto', 'venda__cliente', 'venda__loja', 'venda__vendedor',
    )


def filtrar_produtos_vendidos(queryset: QuerySet, params, *, pode_filtrar_loja: bool) -> QuerySet:
    nome = (params.get('nome') or '').strip()
    if nome:
        queryset = queryset.filter(produto__nome__icontains=nome)
    cpf = somente_digitos(params.get('cpf'))
    if cpf:
        queryset = queryset.filter(venda__cliente__cpf__contains=cpf)
    imei = (params.get('imei') or '').strip()
    if imei:
        queryset = queryset.filter(imei__icontains=imei)
    loja = ler_inteiro(params, 'loja')
    if loja is not None and pode_filtrar_loja:
        queryset = queryset.filter(venda__loja_id=loja)
    canceladas = ler_booleano(params, 'canceladas')
    if canceladas is not None:
        queryset = queryset.filter(venda__is_deleted=canceladas)
    return filtrar_periodo(queryset, params, 'venda__data_venda')


# --- IMEIs disponíveis ----------------------------------------------------------

def imeis_disponiveis(produto_id: int | None = None) -> QuerySet:
    """IMEIs não vendidos nem cancelados e que não estão em outra venda ativa."""
    em_uso = ProdutoVenda.objects.filter(imei=OuterRef('imei'), venda__is_deleted=False)
    queryset = (
        EstoqueImei.objects.select_related('produto', 'loja')
        .filter(~Exists(em_uso), vendido=False, cancelado=False)
    )
    if produto_id is not None:
        queryset = queryset.filter(produto_id=produto_id)
    return queryset.order_by('imei', 'pk')
