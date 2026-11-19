from django.urls import path
from rest_framework.routers import DefaultRouter

from crm import views, views_cadastros

router = DefaultRouter()
router.register('conversas', views.ConversaViewSet, basename='crm-conversa')
router.register('mensagens', views.MensagemViewSet, basename='crm-mensagem')
router.register('programadas', views.ProgramadaViewSet, basename='crm-programada')
router.register('etiquetas', views_cadastros.EtiquetaViewSet, basename='crm-etiqueta')
router.register('respostas-rapidas', views_cadastros.RespostaRapidaViewSet, basename='crm-resposta-rapida')
router.register('aberturas', views_cadastros.AberturaViewSet, basename='crm-abertura')

urlpatterns = [
    path('integracao/', views_cadastros.IntegracaoView.as_view(), name='crm-integracao'),
    path('configuracao/', views_cadastros.ConfiguracaoView.as_view(), name='crm-configuracao'),
    path('atendentes/', views_cadastros.AtendentesView.as_view(), name='crm-atendentes'),
    path('simulador/receber/', views_cadastros.SimuladorReceberView.as_view(), name='crm-simulador-receber'),
    path('simulador/ler/', views_cadastros.SimuladorLerView.as_view(), name='crm-simulador-ler'),
    path('midia/<str:token>/', views.MidiaDownloadView.as_view(), name='crm-midia'),
    *router.urls,
]
