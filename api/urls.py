from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView, DefaultRouter

from . import views

class PublicAPIRootView(APIRootView):
    permission_classes = [AllowAny]


router = DefaultRouter()
router.APIRootView = PublicAPIRootView
router.register("lojas", views.LojaViewSet, basename="loja")
router.register("solicitacoes", views.SolicitacaoCreditoViewSet, basename="solicitacao")
router.register("produtos", views.ProdutoViewSet, basename="produto")

urlpatterns = [
    path("health/", views.health, name="api-health"),
    path("", include(router.urls)),
]
