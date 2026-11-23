"""Tipos de produto: lista, detalhe, criação e edição (sem exclusão, como a tela Django)."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins

from produtos.models import TipoProduto

from ..base import CatalogoViewSet, loja_escolhida
from ..filtros import ler_busca, ordenar
from ..serializers import CatalogoTipoProdutoSerializer

ORDENACAO_TIPOS = {'nome': 'nome', 'criado_em': 'criado_em'}


@extend_schema(tags=['bo-catalogo'])
class TipoProdutoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    CatalogoViewSet,
):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    serializer_class = CatalogoTipoProdutoSerializer
    permissoes = {
        'list': ['produtos.view_tipoproduto'],
        'retrieve': ['produtos.view_tipoproduto'],
        'create': ['produtos.add_tipoproduto'],
        'partial_update': ['produtos.change_tipoproduto'],
    }

    def get_queryset(self):
        tipos = TipoProduto.objects.all()
        if self.action != 'list':
            return tipos
        params = self.request.query_params
        busca = ler_busca(params)
        if busca:
            tipos = tipos.filter(nome__icontains=busca)
        return ordenar(tipos, params, ORDENACAO_TIPOS, padrao=('nome', 'pk'))

    @extend_schema(parameters=[
        OpenApiParameter('busca', OpenApiTypes.STR, description='Nome (contém).'),
        OpenApiParameter('ordenar', OpenApiTypes.STR, description='nome, criado_em (- para decrescente).'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(loja=loja_escolhida(self), criado_por=user, modificado_por=user)

    def perform_update(self, serializer):
        serializer.save(modificado_por=self.request.user)
