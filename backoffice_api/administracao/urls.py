"""Rotas do módulo administracao da API do backoffice (`/api/bo/v1/administracao/`)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AcoesAuditoriaView,
    AuditoriaView,
    BuscaView,
    GrupoViewSet,
    MatrizPermissoesView,
    PerfilView,
    PermissoesView,
    UsuarioViewSet,
)

roteador = SimpleRouter()
roteador.register('usuarios', UsuarioViewSet, basename='usuario')
roteador.register('grupos', GrupoViewSet, basename='grupo')

urlpatterns: list = [
    path('permissoes/', PermissoesView.as_view(), name='permissoes'),
    path('permissoes/matriz/', MatrizPermissoesView.as_view(), name='permissoes-matriz'),
    path('auditoria/', AuditoriaView.as_view(), name='auditoria'),
    path('auditoria/acoes/', AcoesAuditoriaView.as_view(), name='auditoria-acoes'),
    path('perfil/', PerfilView.as_view(), name='perfil'),
    path('busca/', BuscaView.as_view(), name='busca'),
    *roteador.urls,
]
