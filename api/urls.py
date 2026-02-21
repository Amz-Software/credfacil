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
router.register("parcelamentos", views.ParcelamentoViewSet, basename="parcelamento")
router.register("vendas", views.VendaViewSet, basename="venda")
router.register("users", views.UserViewSet, basename="user")
router.register("groups", views.GroupViewSet, basename="group")
router.register("permissions", views.PermissionViewSet, basename="permission")
router.register("usuarios", views.UserViewSet, basename="usuario")
router.register("grupos", views.GroupViewSet, basename="grupo")
router.register("permissoes", views.PermissionViewSet, basename="permissao")

urlpatterns = [
    path("health/", views.health, name="api-health"),
    path("", include(router.urls)),
]
