"""Filtros e ordenação da lista de notificações (`?lida=`, `?busca=`, `?ordenar=`)."""
from django.db.models import Q, QuerySet

from ..nucleo.erros import ErroBackoffice

ORDENACOES = {'criada_em': 'timestamp', '-criada_em': '-timestamp'}
ORDENACAO_PADRAO = '-criada_em'
TAMANHO_MAXIMO_BUSCA = 100
VERDADEIROS = {'true', '1', 'sim'}
FALSOS = {'false', '0', 'nao', 'não'}


def ler_booleano(valor: str | None, campo: str) -> bool | None:
    if valor is None or valor == '':
        return None
    normalizado = valor.strip().lower()
    if normalizado in VERDADEIROS:
        return True
    if normalizado in FALSOS:
        return False
    raise ErroBackoffice('Filtro inválido.', campos={campo: ['Use true ou false.']})


def filtrar_notificacoes(queryset: QuerySet, parametros) -> QuerySet:
    lida = ler_booleano(parametros.get('lida'), 'lida')
    if lida is not None:
        queryset = queryset.filter(unread=not lida)

    busca = (parametros.get('busca') or '').strip()[:TAMANHO_MAXIMO_BUSCA]
    if busca:
        queryset = queryset.filter(Q(verb__icontains=busca) | Q(description__icontains=busca))

    ordenar = parametros.get('ordenar') or ORDENACAO_PADRAO
    if ordenar not in ORDENACOES:
        raise ErroBackoffice('Ordenação inválida.', campos={'ordenar': [f'Use: {", ".join(ORDENACOES)}.']})
    return queryset.order_by(ORDENACOES[ordenar], '-pk')
