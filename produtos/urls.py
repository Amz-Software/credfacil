from django.contrib import admin
from django.urls import path

from produtos.forms import *
from produtos.models import *
from .views import generate_views, ProdutoListView, ProdutoDeleteView, ProdutoActivateView, ParcelamentoDeleteView

app_name = 'produtos'

produtoViews = generate_views(Produto, ProdutoForms, 10, 'produtos')
corProdutoViews = generate_views(CorProduto, CorProdutoForms, 10, 'cor')
tipoViews = generate_views(TipoProduto, TipoForms, 10, 'tipo')
fabricanteViews = generate_views(Fabricante, FabricanteForms, 10, 'fabricante')
estadoViews = generate_views(EstadoProduto, EstadoProdutoForms, 10, 'estado')
memoriaViews = generate_views(MemoriaProduto, MemoriaForms, 10, 'memoria')
parcelamentoViews = generate_views(Parcelamento, ParcelamentoForms, 20, 'parcelamento')


urlpatterns = [
    path('produto/', ProdutoListView.as_view(), name='produtos'),
    path('produtos/novo/', produtoViews['create_view'].as_view(), name='produto_create'),
    path('produtos/detalhe/<int:pk>/', produtoViews['detail_view'].as_view(), name='produto_detail'),
    path('produtos/editar/<int:pk>/', produtoViews['update_view'].as_view(), name='produto_update'),
    path('produtos/deletar/<int:pk>/', ProdutoDeleteView.as_view(), name='produto_delete'),
    path('produtos/ativar/<int:pk>/', ProdutoActivateView.as_view(), name='produto_activate'),

    path('corproduto/', corProdutoViews['list_view'].as_view(), name='cores'),
    path('cor-produto/novo/', corProdutoViews['create_view'].as_view(), name='cor_create'),
    path('cor-produto/detalhe/<int:pk>/', corProdutoViews['detail_view'].as_view(), name='cor_detail'),
    path('cor-produto/editar/<int:pk>/', corProdutoViews['update_view'].as_view(), name='cor_update'),
    path('cor-produto/deletar/<int:pk>/', corProdutoViews['delete_view'].as_view(), name='cor_delete'),

    path('tipoproduto/', tipoViews['list_view'].as_view(), name='tipos'),
    path('tipo/novo/', tipoViews['create_view'].as_view(), name='tipo_create'),
    path('tipo/detalhe/<int:pk>/', tipoViews['detail_view'].as_view(), name='tipo_detail'),
    path('tipo/editar/<int:pk>/', tipoViews['update_view'].as_view(), name='tipo_update'),
    path('tipo/deletar/<int:pk>/', tipoViews['delete_view'].as_view(), name='tipo_delete'),

    path('fabricante/', fabricanteViews['list_view'].as_view(), name='fabricantes'),
    path('fabricante/novo/', fabricanteViews['create_view'].as_view(), name='fabricante_create'),
    path('fabricante/detalhe/<int:pk>/', fabricanteViews['detail_view'].as_view(), name='fabricante_detail'),
    path('fabricante/editar/<int:pk>/', fabricanteViews['update_view'].as_view(), name='fabricante_update'),
    path('fabricante/deletar/<int:pk>/', fabricanteViews['delete_view'].as_view(), name='fabricante_delete'),

    path('estadoproduto/', estadoViews['list_view'].as_view(), name='estados'),
    path('estado/novo/', estadoViews['create_view'].as_view(), name='estado_create'),
    path('estado/detalhe/<int:pk>/', estadoViews['detail_view'].as_view(), name='estado_detail'),
    path('estado/editar/<int:pk>/', estadoViews['update_view'].as_view(), name='estado_update'),
    path('estado/deletar/<int:pk>/', estadoViews['delete_view'].as_view(), name='estado_delete'),

    path('memoriaproduto/', memoriaViews['list_view'].as_view(), name='memorias'),
    path('memoria/novo/', memoriaViews['create_view'].as_view(), name='memoria_create'),
    path('memoria/detalhe/<int:pk>/', memoriaViews['detail_view'].as_view(), name='memoria_detail'),
    path('memoria/editar/<int:pk>/', memoriaViews['update_view'].as_view(), name='memoria_update'),
    path('memoria/deletar/<int:pk>/', memoriaViews['delete_view'].as_view(), name='memoria_delete'),

    path('parcelamento/', parcelamentoViews['list_view'].as_view(), name='parcelamentos'),
    path('parcelamento/novo/', parcelamentoViews['create_view'].as_view(), name='parcelamento_create'),
    path('parcelamento/detalhe/<int:pk>/', parcelamentoViews['detail_view'].as_view(), name='parcelamento_detail'),
    path('parcelamento/editar/<int:pk>/', parcelamentoViews['update_view'].as_view(), name='parcelamento_update'),
    path('parcelamento/deletar/<int:pk>/', ParcelamentoDeleteView.as_view(), name='parcelamento_delete'),

]
