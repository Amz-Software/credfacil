"""Leitura de filtros (query params) e ordenação com lista branca."""
from datetime import date

from django.db.models import QuerySet

from backoffice_api.nucleo.erros import ErroBackoffice

OPCOES_ATIVO = {
    'sim': True, 'true': True, '1': True,
    'nao': False, 'não': False, 'false': False, '0': False,
    'todos': None, 'todas': None,
}


def ler_ativo(params, padrao: str) -> bool | None:
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


def ler_texto(params, nome: str) -> str:
    return (params.get(nome) or '').strip()


def ler_data(params, nome: str) -> date | None:
    valor = ler_texto(params, nome)
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErroBackoffice('Filtro inválido.', campos={nome: ['Use a data no formato AAAA-MM-DD.']})


def ordenar(queryset: QuerySet, params, campos: dict[str, str], padrao: tuple[str, ...]) -> QuerySet:
    valor = ler_texto(params, 'ordenar')
    if not valor:
        return queryset.order_by(*padrao)
    decrescente = valor.startswith('-')
    nome = valor.lstrip('-')
    if nome not in campos:
        permitidos = ', '.join(sorted(campos))
        raise ErroBackoffice('Ordenação inválida.', campos={'ordenar': [f'Use um destes campos: {permitidos}.']})
    campo = campos[nome]
    return queryset.order_by(f'-{campo}' if decrescente else campo, 'pk')
