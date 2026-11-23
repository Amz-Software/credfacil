"""Escopo de lojas: quais lojas o usuário pode ver em cada requisição.

A loja escolhida na interface chega no cabeçalho `X-Loja` (id ou "todas") e é
sempre cruzada com o escopo calculado no servidor; ela nunca concede acesso.
"""
from django.db.models import Q, QuerySet
from rest_framework.request import Request

from vendas.models import Loja

from .erros import PROIBIDO_ACESSO, VALIDACAO, ErroBackoffice

PERMISSAO_TODAS_LOJAS = 'vendas.can_view_all_stores'
CABECALHO_LOJA = 'X-Loja'
TODAS = 'todas'


def tem_acesso_global(user, permissao_global: str | None = None) -> bool:
    """Superusuário, `can_view_all_stores` ou a permissão global do domínio."""
    if user.is_superuser:
        return True
    permissoes = [PERMISSAO_TODAS_LOJAS] + ([permissao_global] if permissao_global else [])
    return any(user.has_perm(p) for p in permissoes)


def escopo_lojas(user, permissao_global: str | None = None) -> QuerySet:
    """Lojas que o usuário pode ver: todas (acesso global) ou as vinculadas a ele.

    Vínculo = usuário da loja, gerente da loja ou a loja principal (`user.loja`).
    """
    if tem_acesso_global(user, permissao_global):
        return Loja.objects.all()
    filtro = Q(usuarios=user) | Q(gerentes=user)
    if user.loja_id:
        filtro |= Q(pk=user.loja_id)
    return Loja.objects.filter(filtro).distinct()


def _valor_cabecalho(request: Request) -> str:
    return (request.headers.get(CABECALHO_LOJA) or '').strip().lower()


def lojas_da_requisicao(request: Request, permissao_global: str | None = None) -> QuerySet:
    """Lojas efetivas da requisição: o escopo inteiro ou a loja pedida em `X-Loja`.

    Levanta 400 para valor inválido e 403 para loja fora do escopo.
    """
    escopo = escopo_lojas(request.user, permissao_global)
    valor = _valor_cabecalho(request)
    if valor in ('', TODAS):
        return escopo
    if not valor.isdigit():
        raise ErroBackoffice('Loja inválida.', codigo=VALIDACAO)
    if not escopo.filter(pk=int(valor)).exists():
        raise ErroBackoffice('Você não tem acesso a esta loja.', codigo=PROIBIDO_ACESSO, status_http=403)
    return Loja.objects.filter(pk=int(valor))


def filtrar_por_lojas(
    queryset: QuerySet,
    request: Request,
    campo: str = 'loja',
    permissao_global: str | None = None,
) -> QuerySet:
    """Restringe `queryset` às lojas da requisição pelo caminho `campo` (ex.: 'venda__loja').

    Com acesso global e sem loja escolhida, não filtra (inclui registros sem loja).
    """
    valor = _valor_cabecalho(request)
    if valor in ('', TODAS) and tem_acesso_global(request.user, permissao_global):
        return queryset
    lojas = lojas_da_requisicao(request, permissao_global)
    return queryset.filter(**{f'{campo}__in': lojas})
