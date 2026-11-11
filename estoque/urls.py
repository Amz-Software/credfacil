from django.urls import path

from .views import (
    EstoqueImeiSearchEditView,
    EstoqueImeiSearchView,
    buscar_imei_por_produto,
    check_produtos,
)

app_name = 'estoque'

# Apenas endpoints de consulta usados pelas telas de venda.
urlpatterns = [
    path('produto/details/<int:produto_id>/', check_produtos, name='produto_details'),
    path('estoque-imei-search/', EstoqueImeiSearchView.as_view(), name='estoque-imei-search'),
    path('estoque-imei-search-edit/', EstoqueImeiSearchEditView.as_view(), name='estoque-imei-search-edit'),
    path('estoque/imei/produto/', buscar_imei_por_produto, name='buscar_imei_por_produto'),
]
