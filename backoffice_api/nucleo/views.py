"""Classes base das views da API do backoffice.

Use `BackofficeAPIView` ou `BackofficeViewSet` em todo endpoint: elas trazem a
sessão do backoffice, as permissões declaradas, o contrato de erro e a paginação.
"""
from django.db.models import QuerySet
from rest_framework import mixins
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from .auditoria import auditar
from .erros import tratar_excecao
from .escopo import filtrar_por_lojas, lojas_da_requisicao
from .paginacao import PaginacaoBackoffice
from .permissoes import AcessoBackoffice, PermissoesDeclaradas
from .sessao import SessaoBackofficeAuthentication


class BackofficeMixin:
    authentication_classes = [SessaoBackofficeAuthentication]
    permission_classes = [AcessoBackoffice, PermissoesDeclaradas]
    pagination_class = PaginacaoBackoffice
    throttle_classes = [UserRateThrottle]
    filter_backends: list = []
    # Mapa de ação/método -> exigências (ver nucleo/permissoes.py). Obrigatório.
    permissoes: dict | None = None
    # Permissão que libera todas as lojas neste domínio (ex.: 'vendas.can_view_all_sales').
    permissao_global_lojas: str | None = None

    def get_exception_handler(self):
        return tratar_excecao

    def lojas(self) -> QuerySet:
        return lojas_da_requisicao(self.request, self.permissao_global_lojas)

    def filtrar_por_lojas(self, queryset: QuerySet, campo: str = 'loja') -> QuerySet:
        return filtrar_por_lojas(queryset, self.request, campo, self.permissao_global_lojas)

    def auditar(self, acao: str, **kwargs):
        return auditar(self.request, acao, **kwargs)


class BackofficeAPIView(BackofficeMixin, APIView):
    """APIView do backoffice; `paginar()` aplica a paginação padrão."""

    def paginar(self, queryset: QuerySet, serializer_class, **contexto) -> Response:
        paginador = self.pagination_class()
        pagina = paginador.paginate_queryset(queryset, self.request, view=self)
        contexto.setdefault('request', self.request)
        dados = serializer_class(pagina, many=True, context=contexto).data
        return paginador.get_paginated_response(dados)


class BackofficeViewSet(BackofficeMixin, GenericViewSet):
    """ViewSet genérico; combine com os mixins de `rest_framework.mixins` conforme a necessidade."""


class BackofficeReadOnlyViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, BackofficeViewSet):
    pass


class BackofficeModelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    BackofficeViewSet,
):
    pass
