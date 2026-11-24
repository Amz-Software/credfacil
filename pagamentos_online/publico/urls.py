"""Rotas do app do cliente (`/api/publico/v1/`)."""
from django.urls import path

from . import views

app_name = 'publico'

urlpatterns = [
    path('consulta/', views.ConsultaView.as_view(), name='consulta'),
    path('pagamentos/<uuid:token>/', views.PagamentoView.as_view(), name='pagamento'),
    path('pagamentos/<uuid:token>/informar-quitacao/', views.InformarQuitacaoView.as_view(), name='informar-quitacao'),
    path('pagamentos/<uuid:token>/parcelas/<int:pk>/opcoes/', views.OpcoesView.as_view(), name='opcoes'),
    path('pagamentos/<uuid:token>/parcelas/<int:pk>/cobrancas/', views.CriarCobrancaView.as_view(), name='cobrancas'),
    path('pagamentos/<uuid:token>/parcelas/<int:pk>/informar/', views.InformarPagamentoView.as_view(), name='informar'),
    path('pagamentos/<uuid:token>/cobrancas/<uuid:referencia>/', views.CobrancaView.as_view(), name='cobranca'),
    path(
        'pagamentos/<uuid:token>/cobrancas/<uuid:referencia>/comprovante/',
        views.ComprovanteView.as_view(), name='comprovante',
    ),
]
