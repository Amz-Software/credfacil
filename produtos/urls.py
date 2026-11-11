from django.contrib import admin
from django.urls import path

from produtos.forms import *
from produtos.models import *
from .views import generate_views, ProdutoListView, ProdutoDeleteView, ProdutoActivateView, ParcelamentoDeleteView, ProdutoPDFView, MarcaActivateView, MarcaDeactivateView

app_name = 'produtos'

produtoViews = generate_views(Produto, ProdutoForms, 10, 'produtos')
tipoViews = generate_views(TipoProduto, TipoForms, 10, 'tipo')
marcaViews = generate_views(Marca, MarcaForms, 10, 'marca')
parcelamentoViews = generate_views(Parcelamento, ParcelamentoForms, 20, 'parcelamento')


urlpatterns = [
    path('produto/', ProdutoListView.as_view(), name='produtos'),
    path('produto/pdf/', ProdutoPDFView.as_view(), name='produto_pdf'),
    path('produtos/novo/', produtoViews['create_view'].as_view(), name='produto_create'),
    path('produtos/detalhe/<int:pk>/', produtoViews['detail_view'].as_view(), name='produto_detail'),
    path('produtos/editar/<int:pk>/', produtoViews['update_view'].as_view(), name='produto_update'),
    path('produtos/deletar/<int:pk>/', ProdutoDeleteView.as_view(), name='produto_delete'),
    path('produtos/ativar/<int:pk>/', ProdutoActivateView.as_view(), name='produto_activate'),

    path('tipoproduto/', tipoViews['list_view'].as_view(), name='tipos'),
    path('tipo/novo/', tipoViews['create_view'].as_view(), name='tipo_create'),
    path('tipo/detalhe/<int:pk>/', tipoViews['detail_view'].as_view(), name='tipo_detail'),
    path('tipo/editar/<int:pk>/', tipoViews['update_view'].as_view(), name='tipo_update'),

    path('marca/', marcaViews['list_view'].as_view(), name='marcas'),
    path('marca/novo/', marcaViews['create_view'].as_view(), name='marca_create'),
    path('marca/detalhe/<int:pk>/', marcaViews['detail_view'].as_view(), name='marca_detail'),
    path('marca/editar/<int:pk>/', marcaViews['update_view'].as_view(), name='marca_update'),
    path('marca/desativar/<int:pk>/', MarcaDeactivateView.as_view(), name='marca_deactivate'),
    path('marca/ativar/<int:pk>/', MarcaActivateView.as_view(), name='marca_activate'),

    path('parcelamento/', parcelamentoViews['list_view'].as_view(), name='parcelamentos'),
    path('parcelamento/novo/', parcelamentoViews['create_view'].as_view(), name='parcelamento_create'),
    path('parcelamento/detalhe/<int:pk>/', parcelamentoViews['detail_view'].as_view(), name='parcelamento_detail'),
    path('parcelamento/editar/<int:pk>/', parcelamentoViews['update_view'].as_view(), name='parcelamento_update'),
    path('parcelamento/deletar/<int:pk>/', ParcelamentoDeleteView.as_view(), name='parcelamento_delete'),

]
