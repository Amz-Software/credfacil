"""Rotas do módulo vendas da API do backoffice (`/api/bo/v1/vendas/`)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import VendaViewSet
from .views_apoio import AutorizacaoGerenteView, ProdutosVendidosView

roteador = SimpleRouter()
roteador.register('', VendaViewSet, basename='venda')

urlpatterns = [
    path('produtos-vendidos/', ProdutosVendidosView.as_view(), name='produtos-vendidos'),
    path('autorizacao-gerente/', AutorizacaoGerenteView.as_view(), name='autorizacao-gerente'),
    path('<int:pk>/nota.pdf', VendaViewSet.as_view({'get': 'nota_pdf'}), name='venda-nota-pdf'),
    path('<int:pk>/carne.pdf', VendaViewSet.as_view({'get': 'carne_pdf'}), name='venda-carne-pdf'),
    path('<int:pk>/contrato.pdf', VendaViewSet.as_view({'get': 'contrato_pdf'}), name='venda-contrato-pdf'),
] + roteador.urls
