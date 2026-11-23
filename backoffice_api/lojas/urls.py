"""Rotas do módulo lojas da API do backoffice (`/api/bo/v1/lojas/`)."""
from django.urls import path

from . import views

numeros = views.NumerosAutenticadoresViewSet
numeros_lista = numeros.as_view({'get': 'list', 'post': 'create'})
numeros_item = numeros.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('', views.LojasView.as_view(), name='lojas'),
    path('repasses/', views.RepassesView.as_view(), name='repasses'),
    path('repasses/agendados/', views.RepassesAgendadosView.as_view(), name='repasses-agendados'),
    path('repasses/<int:pk>/', views.RepasseView.as_view(), name='repasse'),
    path('numeros-autenticadores/', numeros_lista, name='numeros-autenticadores'),
    path('numeros-autenticadores/<int:pk>/', numeros_item, name='numero-autenticador'),
    path('<int:pk>/', views.LojaDetalheView.as_view(), name='loja'),
    path('<int:pk>/vendas/', views.LojaVendasView.as_view(), name='loja-vendas'),
    path('<int:pk>/logo/', views.LojaLogoView.as_view(), name='loja-logo'),
    path('<int:pk>/qrcode/', views.LojaQrCodeView.as_view(), name='loja-qrcode'),
    path('<int:pk>/replicar-qrcode/', views.ReplicarQrCodeView.as_view(), name='loja-replicar-qrcode'),
]
