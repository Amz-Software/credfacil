"""Parcelamentos (juros e desconto por marca e nº de vezes): CRUD com exclusão definitiva.

Só aparecem os parcelamentos de marcas visíveis para as lojas da requisição (ou sem
marca). Criação, edição e exclusão ficam na auditoria: a tabela define os juros das
vendas geradas a partir das análises.
"""
from django.db import transaction
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.response import Response

from produtos.models import Parcelamento

from ..base import CatalogoViewSet, loja_escolhida, lojas_para_filtro
from ..filtros import ler_busca, ler_id, ordenar
from ..serializers import CatalogoParcelamentoEntradaSerializer, CatalogoParcelamentoSerializer
from ..servicos import marcas_visiveis

ORDENACAO_PARCELAMENTOS = {
    'marca': 'marca__nome',
    'qtd_vezes': 'qtd_vezes',
    'porcentagem_juros': 'porcentagem_juros',
    'porcentagem_desconto': 'porcentagem_desconto',
}


def _retrato(parcelamento: Parcelamento) -> dict:
    return {
        'marca': parcelamento.marca.nome if parcelamento.marca else None,
        'qtd_vezes': parcelamento.qtd_vezes,
        'porcentagem_juros': str(parcelamento.porcentagem_juros),
        'porcentagem_desconto': str(parcelamento.porcentagem_desconto),
    }


@extend_schema(tags=['bo-catalogo'])
class ParcelamentoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, CatalogoViewSet):
    serializer_class = CatalogoParcelamentoSerializer
    permissoes = {
        'list': ['produtos.view_parcelamento'],
        'retrieve': ['produtos.view_parcelamento'],
        'create': ['produtos.add_parcelamento'],
        'partial_update': ['produtos.change_parcelamento'],
        'destroy': ['produtos.delete_parcelamento'],
    }

    def _marcas(self):
        return marcas_visiveis(lojas_para_filtro(self))

    def get_queryset(self):
        parcelamentos = Parcelamento.objects.select_related('marca').filter(
            Q(marca__isnull=True) | Q(marca__in=self._marcas())
        )
        if self.action != 'list':
            return parcelamentos
        params = self.request.query_params
        busca = ler_busca(params)
        if busca:
            filtro = Q(marca__nome__icontains=busca)
            if busca.isdigit():
                filtro |= Q(qtd_vezes=int(busca))
            parcelamentos = parcelamentos.filter(filtro)
        marca = ler_id(params, 'marca')
        if marca is not None:
            parcelamentos = parcelamentos.filter(marca_id=marca)
        return ordenar(parcelamentos, params, ORDENACAO_PARCELAMENTOS, padrao=('marca__nome', 'qtd_vezes', 'pk'))

    def _contexto_entrada(self) -> dict:
        return {'request': self.request, 'marcas': self._marcas()}

    def _detalhe(self, parcelamento: Parcelamento) -> dict:
        recarregado = Parcelamento.objects.select_related('marca').get(pk=parcelamento.pk)
        return CatalogoParcelamentoSerializer(recarregado, context={'request': self.request}).data

    @extend_schema(parameters=[
        OpenApiParameter('busca', OpenApiTypes.STR, description='Nome da marca (contém) ou nº de vezes.'),
        OpenApiParameter('marca', OpenApiTypes.INT),
        OpenApiParameter('ordenar', OpenApiTypes.STR,
                         description='marca, qtd_vezes, porcentagem_juros, porcentagem_desconto (- para decrescente).'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=CatalogoParcelamentoEntradaSerializer, responses={201: CatalogoParcelamentoSerializer})
    def create(self, request):
        entrada = CatalogoParcelamentoEntradaSerializer(data=request.data, context=self._contexto_entrada())
        entrada.is_valid(raise_exception=True)
        user = request.user
        with transaction.atomic():
            parcelamento = entrada.save(loja=loja_escolhida(self), criado_por=user, modificado_por=user)
            self.auditar('parcelamento_criado', objeto=parcelamento, descricao=str(parcelamento),
                         dados={'depois': _retrato(parcelamento)})
        return Response(self._detalhe(parcelamento), status=status.HTTP_201_CREATED)

    @extend_schema(request=CatalogoParcelamentoEntradaSerializer, responses=CatalogoParcelamentoSerializer)
    def partial_update(self, request, pk=None):
        parcelamento = self.get_object()
        antes = _retrato(parcelamento)
        entrada = CatalogoParcelamentoEntradaSerializer(
            parcelamento, data=request.data, partial=True, context=self._contexto_entrada()
        )
        entrada.is_valid(raise_exception=True)
        with transaction.atomic():
            parcelamento = entrada.save(modificado_por=request.user)
            depois = _retrato(parcelamento)
            if depois != antes:
                self.auditar('parcelamento_alterado', objeto=parcelamento, descricao=str(parcelamento),
                             dados={'antes': antes, 'depois': depois})
        return Response(self._detalhe(parcelamento))

    @extend_schema(responses={204: None})
    def destroy(self, request, pk=None):
        parcelamento = self.get_object()
        with transaction.atomic():
            self.auditar('parcelamento_excluido', objeto=parcelamento, descricao=str(parcelamento),
                         dados={'antes': _retrato(parcelamento)})
            parcelamento.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
