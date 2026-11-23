"""Rotas do módulo notificacoes da API do backoffice (`/api/bo/v1/notificacoes/`)."""
from django.urls import path

from . import views

urlpatterns = [
    path('', views.NotificacaoListaView.as_view(), name='lista'),
    path('nao-lidas/', views.NotificacaoNaoLidasView.as_view(), name='nao-lidas'),
    path('marcar-lidas/', views.NotificacaoMarcarSelecionadasView.as_view(), name='marcar-lidas'),
    path('marcar-todas-lidas/', views.NotificacaoMarcarTodasView.as_view(), name='marcar-todas-lidas'),
    path('<int:pk>/marcar-lida/', views.NotificacaoMarcarLidaView.as_view(), name='marcar-lida'),
]
