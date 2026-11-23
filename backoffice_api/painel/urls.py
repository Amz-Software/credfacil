"""Rotas do módulo painel da API do backoffice."""
from django.urls import path

from .views import PainelGraficosPdfView, PainelGraficosView, PainelResumoView

urlpatterns: list = [
    path('resumo/', PainelResumoView.as_view(), name='resumo'),
    path('graficos/', PainelGraficosView.as_view(), name='graficos'),
    path('graficos/relatorio.pdf', PainelGraficosPdfView.as_view(), name='graficos_pdf'),
]
