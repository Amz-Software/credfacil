"""Escopo de lojas da API do vendedor (`/api/`).

O usuário só vê e age sobre objetos das lojas a que está vinculado: usuário da
loja (`user.lojas`), gerente (`user.lojas_gerenciadas`) ou a loja principal
(`user.loja`). Superusuário e quem tem a permissão global do domínio veem tudo.
"""
from django.db.models import QuerySet

PERMISSAO_TODAS_LOJAS = "vendas.can_view_all_stores"
PERMISSAO_TODAS_ANALISES = "vendas.view_all_analise_credito"


def tem_acesso_global(user, permissoes_globais: tuple[str, ...] = (PERMISSAO_TODAS_LOJAS,)) -> bool:
    if user.is_superuser:
        return True
    return any(user.has_perm(permissao) for permissao in permissoes_globais)


def ids_lojas_do_usuario(user) -> set[int]:
    ids = set(user.lojas.values_list("id", flat=True))
    ids |= set(user.lojas_gerenciadas.values_list("id", flat=True))
    if getattr(user, "loja_id", None):
        ids.add(user.loja_id)
    return ids


def filtrar_por_escopo(
    queryset: QuerySet,
    user,
    campo: str = "loja",
    permissoes_globais: tuple[str, ...] = (PERMISSAO_TODAS_LOJAS,),
) -> QuerySet:
    """Restringe `queryset` às lojas do usuário pelo caminho `campo` (ex.: 'venda__loja')."""
    if tem_acesso_global(user, permissoes_globais):
        return queryset
    return queryset.filter(**{f"{campo}__in": ids_lojas_do_usuario(user)})


def loja_no_escopo(
    user,
    loja_id: int | None,
    permissoes_globais: tuple[str, ...] = (PERMISSAO_TODAS_LOJAS,),
) -> bool:
    if tem_acesso_global(user, permissoes_globais):
        return True
    return loja_id is not None and loja_id in ids_lojas_do_usuario(user)
