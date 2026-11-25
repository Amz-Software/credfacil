"""Rotas de pagamentos online da API do backoffice (`/api/bo/v1/cobrancas_online/`)."""
from django.urls import path

from . import views

urlpatterns = [
    path('configuracao/', views.ConfiguracaoView.as_view(), name='configuracao'),
    path('cobrancas/', views.CobrancasListaView.as_view(), name='cobrancas'),
    path('registros/', views.RegistrosView.as_view(), name='registros'),
    path('parcelas/<int:pk>/cobrancas/', views.ParcelaCobrancasView.as_view(), name='parcela-cobrancas'),
    path('pagamentos/<int:pk>/cobrancas/', views.PagamentoCobrancasView.as_view(), name='pagamento-cobrancas'),
    path('pagamentos/<int:pk>/opcoes/', views.PagamentoOpcoesView.as_view(), name='pagamento-opcoes'),
    path('parcelas/<int:pk>/enviar-link/', views.EnviarLinkView.as_view(), name='parcela-enviar-link'),
]
