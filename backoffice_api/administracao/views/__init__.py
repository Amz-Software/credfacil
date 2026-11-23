"""Views da administração (usuários, grupos, permissões, auditoria, perfil e busca)."""
from .consultas import (  # noqa: F401
    AcoesAuditoriaView,
    AuditoriaView,
    BuscaView,
    MatrizPermissoesView,
    PerfilView,
    PermissoesView,
)
from .grupos import GrupoViewSet  # noqa: F401
from .usuarios import UsuarioViewSet  # noqa: F401
