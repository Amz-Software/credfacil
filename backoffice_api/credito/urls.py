"""Rotas do módulo credito da API do backoffice (`/api/bo/v1/credito/`)."""
from django.urls import path
from rest_framework.routers import SimpleRouter

from .views.busca import BuscaSolicitacoesView
from .views.pre_analises import PreAnaliseViewSet, RelatorioPreAnalisesView
from .views.solicitacoes import SolicitacaoViewSet

router = SimpleRouter()
router.register('solicitacoes', SolicitacaoViewSet, basename='solicitacao')
router.register('pre-analises', PreAnaliseViewSet, basename='pre-analise')

urlpatterns = [
    path('busca/', BuscaSolicitacoesView.as_view(), name='busca'),
    # Antes do router: sem isto "relatorio.pdf" seria lido como id de pré-análise.
    path('pre-analises/relatorio.pdf', RelatorioPreAnalisesView.as_view(), name='pre-analise-relatorio'),
    *router.urls,
]
