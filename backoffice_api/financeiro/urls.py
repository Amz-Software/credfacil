"""Rotas do módulo financeiro da API do backoffice (`/api/bo/v1/financeiro/`)."""
from django.urls import path

from . import views

urlpatterns = [
    path('contas-a-receber/', views.ContasAReceberListaView.as_view(), name='contas-lista'),
    path('contas-a-receber/<int:pk>/', views.ContaAReceberDetalheView.as_view(), name='conta-detalhe'),
    path('contas-a-receber/<int:pk>/situacoes/', views.SituacoesView.as_view(), name='conta-situacoes'),
    path('contas-a-receber/<int:pk>/quitar/', views.QuitarView.as_view(), name='conta-quitar'),
    path('contas-a-receber/<int:pk>/parcelas/', views.AdicionarParcelasView.as_view(), name='conta-parcelas'),
    path('contas-a-receber/<int:pk>/contatos/', views.ContatoCriarView.as_view(), name='conta-contatos'),
    path(
        'contas-a-receber/<int:pk>/contatos/<int:contato_pk>/',
        views.ContatoEditarView.as_view(),
        name='conta-contato',
    ),
    path('contas-a-receber/<int:pk>/bo/previa/', views.BoPreviaView.as_view(), name='conta-bo-previa'),
    path('contas-a-receber/<int:pk>/bo/pdf/', views.BoPdfView.as_view(), name='conta-bo-pdf'),
    path('parcelas/<int:pk>/', views.ParcelaView.as_view(), name='parcela'),
    path('parcelas/<int:pk>/comprovantes/', views.ComprovanteUploadView.as_view(), name='parcela-comprovantes'),
    path('comprovantes/<int:pk>/', views.ComprovanteView.as_view(), name='comprovante'),
    path('comprovantes/<int:pk>/arquivo/', views.ComprovanteArquivoView.as_view(), name='comprovante-arquivo'),
    path('status-pagamento/', views.StatusPagamentoListaView.as_view(), name='status-pagamento'),
]
