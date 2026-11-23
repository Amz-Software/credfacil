"""Leitura dos filtros de lista do catálogo (query params) e ordenação com lista branca."""
from django.db.models import Q, QuerySet

from backoffice_api.nucleo.erros import ErroBackoffice

# Valores aceitos em `?ativo=`; None = não filtra.
OPCOES_ATIVO = {
    'sim': True, 'true': True, '1': True,
    'nao': False, 'não': False, 'false': False, '0': False,
    'todos': None, 'todas': None,
}


def ler_ativo(params, padrao: str) -> bool | None:
    """`?ativo=sim|nao|todos` (aceita também true/false/1/0)."""
    valor = (params.get('ativo') or padrao).strip().lower()
    if valor not in OPCOES_ATIVO:
        raise ErroBackoffice('Filtro inválido.', campos={'ativo': ['Use sim, nao ou todos.']})
    return OPCOES_ATIVO[valor]


def ler_id(params, nome: str) -> int | None:
    valor = (params.get(nome) or '').strip()
    if not valor:
        return None
    if not valor.isdigit():
        raise ErroBackoffice('Filtro inválido.', campos={nome: ['Informe um número.']})
    return int(valor)


def ler_busca(params) -> str:
    return (params.get('busca') or '').strip()


def ordenar(queryset: QuerySet, params, campos: dict[str, str], padrao: tuple[str, ...]) -> QuerySet:
    """`?ordenar=campo|-campo`, só com os nomes de `campos` (nome da API -> caminho no ORM)."""
    valor = (params.get('ordenar') or '').strip()
    if not valor:
        return queryset.order_by(*padrao)
    decrescente = valor.startswith('-')
    nome = valor.lstrip('-')
    if nome not in campos:
        permitidos = ', '.join(sorted(campos))
        raise ErroBackoffice('Ordenação inválida.', campos={'ordenar': [f'Use um destes campos: {permitidos}.']})
    campo = campos[nome]
    return queryset.order_by(f'-{campo}' if decrescente else campo, 'pk')


def filtrar_produtos(queryset: QuerySet, params, *, pode_ver_inativos: bool) -> QuerySet:
    """Busca (nome ou código), marca e situação; sem `view_all_produtos` só ativos."""
    busca = ler_busca(params)
    if busca:
        filtro = Q(nome__icontains=busca)
        if busca.isdigit():
            filtro |= Q(codigo=int(busca))
        queryset = queryset.filter(filtro)
    marca = ler_id(params, 'marca')
    if marca is not None:
        queryset = queryset.filter(marca_id=marca)
    ativo = ler_ativo(params, padrao='todos') if pode_ver_inativos else True
    if ativo is not None:
        queryset = queryset.filter(ativo=ativo)
    return queryset


ORDENACAO_PRODUTOS = {
    'nome': 'nome',
    'codigo': 'codigo',
    'valor': 'valor',
    'entrada_cliente': 'entrada_cliente',
    'criado_em': 'criado_em',
}
