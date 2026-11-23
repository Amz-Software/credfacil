"""Base das views de lojas: escopo de loja e 405 antes do 403."""
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions

from vendas.models import Loja

from ..nucleo.views import BackofficeAPIView, BackofficeViewSet

TAGS = ['bo-lojas']


class MetodoNaoPermitidoAntesMixin:
    """Método sem handler responde 405 (e não 403 por não estar em `permissoes`).

    Mesmo comportamento de `backoffice_api.financeiro.base`; candidato a ir para o núcleo.
    """

    def check_permissions(self, request):
        metodo = request.method.lower()
        autenticado = bool(request.user and request.user.is_authenticated)
        if autenticado and (metodo not in self.http_method_names or not hasattr(self, metodo)):
            raise exceptions.MethodNotAllowed(request.method)
        super().check_permissions(request)


class EscopoLojasMixin:
    def lojas_visiveis(self) -> QuerySet:
        return self.filtrar_por_lojas(Loja.objects.all(), 'pk')

    def obter_loja(self, pk: int) -> Loja:
        return get_object_or_404(self.lojas_visiveis(), pk=pk)


class LojasBaseView(MetodoNaoPermitidoAntesMixin, EscopoLojasMixin, BackofficeAPIView):
    pass


class LojasBaseViewSet(MetodoNaoPermitidoAntesMixin, EscopoLojasMixin, BackofficeViewSet):
    pass
