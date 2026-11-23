"""Rotas do módulo catalogo da API do backoffice (`/api/bo/v1/catalogo/`)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import MarcaViewSet, ParcelamentoViewSet, ProdutoRelatorioPDFView, ProdutoViewSet, TipoProdutoViewSet

roteador = SimpleRouter()
roteador.register('produtos', ProdutoViewSet, basename='produto')
roteador.register('tipos', TipoProdutoViewSet, basename='tipo')
roteador.register('marcas', MarcaViewSet, basename='marca')
roteador.register('parcelamentos', ParcelamentoViewSet, basename='parcelamento')

urlpatterns: list = [
    path('produtos/relatorio.pdf', ProdutoRelatorioPDFView.as_view(), name='produtos-relatorio'),
    *roteador.urls,
]
