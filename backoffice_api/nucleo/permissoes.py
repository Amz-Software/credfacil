"""Permissões da API do backoffice.

Toda view declara `permissoes`, um dicionário de ação (viewsets) ou método HTTP
(APIView) para a lista de exigências. Ação não declarada é negada.

    permissoes = {
        'list': ['vendas.view_cliente'],
        'aprovar': ['vendas.change_status_analise'],
        'reprovar': [QualquerPermissao('vendas.change_status_analise', 'vendas.change_cliente')],
        'observar': [EmGrupo('ANALISTA', 'ADMINISTRADOR')],
        'GET': [],   # lista vazia: basta ter acesso ao backoffice
    }
"""
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .erros import PROIBIDO_ACESSO, TROCA_SENHA_OBRIGATORIA
from .sessao import CHAVE_TROCAR_SENHA

PERMISSAO_ACESSO = 'backoffice_api.acessar_backoffice'


class PermissaoNegada(PermissionDenied):
    def __init__(self, mensagem: str, codigo: str = PROIBIDO_ACESSO):
        super().__init__(mensagem)
        self.codigo = codigo


class QualquerPermissao:
    """Exigência satisfeita por qualquer uma das permissões listadas."""

    def __init__(self, *permissoes: str):
        self.permissoes = permissoes

    def avaliar(self, user) -> bool:
        return any(user.has_perm(p) for p in self.permissoes)


class EmGrupo:
    """Exigência satisfeita por pertencer a um dos grupos (ou ser superusuário)."""

    def __init__(self, *grupos: str):
        self.grupos = grupos

    def avaliar(self, user) -> bool:
        return user.is_superuser or user.groups.filter(name__in=self.grupos).exists()


def tem_acesso_backoffice(user) -> bool:
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_superuser or user.has_perm(PERMISSAO_ACESSO))
    )


class AcessoBackoffice(BasePermission):
    """Usuário ativo com `acessar_backoffice` e sem troca de senha pendente."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if not tem_acesso_backoffice(user):
            raise PermissaoNegada('Seu usuário não tem acesso ao backoffice.')
        pendente = request.session.get(CHAVE_TROCAR_SENHA, False)
        if pendente and not getattr(view, 'permite_com_troca_de_senha_pendente', False):
            raise PermissaoNegada(
                'Sua senha não atende à política atual. Troque a senha para continuar.',
                codigo=TROCA_SENHA_OBRIGATORIA,
            )
        return True


def _atende(item, request, view) -> bool:
    user = request.user
    if hasattr(item, 'avaliar'):
        return item.avaliar(user)
    if callable(item):
        return bool(item(request, view))
    return user.has_perm(item)


class PermissoesDeclaradas(BasePermission):
    """Confere `view.permissoes[acao ou método]`; o que não estiver declarado é negado."""

    def has_permission(self, request, view) -> bool:
        mapa = getattr(view, 'permissoes', None)
        if mapa is None:
            return False
        chave = getattr(view, 'action', None) or request.method
        if chave not in mapa:
            return False
        if request.user.is_superuser:
            return True
        return all(_atende(item, request, view) for item in (mapa[chave] or []))
