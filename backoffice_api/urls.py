"""Rotas da API do backoffice (`/api/bo/v1/`).

Cada módulo tem o próprio `urls.py` e namespace (`backoffice_api:<modulo>:<nome>`).
"""
from django.urls import include, path

app_name = 'backoffice_api'

MODULOS = (
    'painel',
    'notificacoes',
    'credito',
    'vendas',
    'financeiro',
    'lojas',
    'catalogo',
    'administracao',
    'relatorios',
    'crm',
)

urlpatterns = [
    path('', include('backoffice_api.autenticacao.urls')),
] + [
    path(f'{modulo}/', include((f'backoffice_api.{modulo}.urls', modulo)))
    for modulo in MODULOS
]
