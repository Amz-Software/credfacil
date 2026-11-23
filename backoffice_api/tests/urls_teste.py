"""URLconf só de teste: views mínimas para exercitar o núcleo da API do backoffice."""
from django.http import Http404
from django.urls import include, path
from rest_framework.response import Response

from backoffice_api.nucleo.views import BackofficeAPIView


class EscopoView(BackofficeAPIView):
    """Devolve os ids das lojas efetivas da requisição."""

    permissoes = {'GET': []}

    def get(self, request):
        return Response(sorted(self.lojas().values_list('pk', flat=True)))


class ProtegidaView(BackofficeAPIView):
    permissoes = {'GET': ['vendas.view_cliente']}

    def get(self, request):
        return Response({'ok': True})


class SemDeclaracaoView(BackofficeAPIView):
    def get(self, request):
        return Response({'ok': True})


class ErroView(BackofficeAPIView):
    permissoes = {'GET': []}

    def get(self, request):
        tipo = request.query_params.get('tipo')
        if tipo == '404':
            raise Http404
        if tipo == 'negocio':
            from vendas.services.erros import ErroDeNegocio

            raise ErroDeNegocio('Marca sem parcelamento cadastrado.')
        raise RuntimeError('falha inesperada')


urlpatterns = [
    path('api/bo/v1/', include('backoffice_api.urls', namespace='backoffice_api')),
    path('api/bo/v1/teste/escopo/', EscopoView.as_view()),
    path('api/bo/v1/teste/protegida/', ProtegidaView.as_view()),
    path('api/bo/v1/teste/sem-declaracao/', SemDeclaracaoView.as_view()),
    path('api/bo/v1/teste/erro/', ErroView.as_view()),
]
