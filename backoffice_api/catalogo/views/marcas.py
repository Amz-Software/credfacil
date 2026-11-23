"""Marcas: lista (escopo de lojas permitidas), detalhe, criação, edição e ativar/desativar."""
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Prefetch, Subquery, Value
from django.db.models.functions import Coalesce
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from backoffice_api.nucleo.permissoes import QualquerPermissao
from produtos.models import Marca, Parcelamento, Produto
from vendas.models import Loja

from ..base import CatalogoViewSet, ids_escopo_de_escrita, loja_escolhida, lojas_para_filtro
from ..filtros import ler_ativo, ler_busca, ordenar
from ..serializers import CatalogoIconeMarcaSerializer, CatalogoMarcaEntradaSerializer, CatalogoMarcaSerializer, CatalogoMotivoOpcionalSerializer
from ..servicos import marcas_visiveis, mesclar_lojas

VER = 'produtos.view_marca'
CRIAR = 'produtos.add_marca'
ALTERAR = 'produtos.change_marca'
ORDENACAO_MARCAS = {'nome': 'nome', 'criado_em': 'criado_em'}


def _contagem(modelo, campo: str) -> Coalesce:
    subconsulta = (
        modelo.objects.filter(**{campo: OuterRef('pk')})
        .order_by().values(campo).annotate(total=Count('pk')).values('total')
    )
    return Coalesce(Subquery(subconsulta, output_field=IntegerField()), Value(0))


@extend_schema(tags=['bo-catalogo'])
class MarcaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, CatalogoViewSet):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    serializer_class = CatalogoMarcaSerializer
    permissoes = {
        'list': [VER],
        'retrieve': [VER],
        'icones': [QualquerPermissao(VER, CRIAR, ALTERAR)],
        'create': [CRIAR],
        'partial_update': [ALTERAR],
        'ativar': [ALTERAR],
        'desativar': [ALTERAR],
    }

    def _lojas_exibidas(self):
        escopo = ids_escopo_de_escrita(self)
        lojas = Loja.objects.order_by('nome')
        return lojas if escopo is None else lojas.filter(pk__in=escopo)

    def _anotar(self, marcas):
        return marcas.annotate(
            total_produtos=_contagem(Produto, 'marca'),
            total_parcelamentos=_contagem(Parcelamento, 'marca'),
        ).prefetch_related(Prefetch('lojas_permitidas', queryset=self._lojas_exibidas()))

    def get_queryset(self):
        marcas = self._anotar(marcas_visiveis(lojas_para_filtro(self)))
        if self.action != 'list':
            return marcas
        params = self.request.query_params
        ativo = ler_ativo(params, padrao='sim')
        if ativo is not None:
            marcas = marcas.filter(ativo=ativo)
        busca = ler_busca(params)
        if busca:
            marcas = marcas.filter(nome__icontains=busca)
        return ordenar(marcas, params, ORDENACAO_MARCAS, padrao=('nome', 'pk'))

    def _detalhe(self, marca: Marca) -> dict:
        recarregada = self._anotar(Marca.objects.filter(pk=marca.pk)).get()
        return CatalogoMarcaSerializer(recarregada, context={'request': self.request}).data

    def _contexto_entrada(self) -> dict:
        return {'request': self.request, 'escopo_escrita': ids_escopo_de_escrita(self)}

    def _gravar_lojas(self, marca: Marca, lojas: list | None) -> None:
        if lojas is None:
            return
        atuais = set(marca.lojas_permitidas.values_list('pk', flat=True))
        finais = mesclar_lojas(atuais, {loja.pk for loja in lojas}, ids_escopo_de_escrita(self))
        marca.lojas_permitidas.set(finais)

    @extend_schema(parameters=[
        OpenApiParameter('ativo', OpenApiTypes.STR, enum=['sim', 'nao', 'todos'], description='Padrão: sim.'),
        OpenApiParameter('busca', OpenApiTypes.STR, description='Nome (contém).'),
        OpenApiParameter('ordenar', OpenApiTypes.STR, description='nome, criado_em (- para decrescente).'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=CatalogoMarcaEntradaSerializer, responses={201: CatalogoMarcaSerializer})
    def create(self, request):
        entrada = CatalogoMarcaEntradaSerializer(data=request.data, context=self._contexto_entrada())
        entrada.is_valid(raise_exception=True)
        dados = dict(entrada.validated_data)
        lojas = dados.pop('lojas_permitidas', None)
        user = request.user
        with transaction.atomic():
            marca = Marca.objects.create(**dados, loja=loja_escolhida(self), criado_por=user, modificado_por=user)
            self._gravar_lojas(marca, lojas)
        return Response(self._detalhe(marca), status=status.HTTP_201_CREATED)

    @extend_schema(request=CatalogoMarcaEntradaSerializer, responses=CatalogoMarcaSerializer)
    def partial_update(self, request, pk=None):
        marca = self.get_object()
        entrada = CatalogoMarcaEntradaSerializer(marca, data=request.data, partial=True, context=self._contexto_entrada())
        entrada.is_valid(raise_exception=True)
        dados = dict(entrada.validated_data)
        lojas = dados.pop('lojas_permitidas', None)
        with transaction.atomic():
            for campo, valor in dados.items():
                setattr(marca, campo, valor)
            marca.save(user=request.user)
            self._gravar_lojas(marca, lojas)
        return Response(self._detalhe(marca))

    def _alterar_situacao(self, ativo: bool) -> Response:
        marca = self.get_object()
        entrada = CatalogoMotivoOpcionalSerializer(data=self.request.data)
        entrada.is_valid(raise_exception=True)
        if marca.ativo != ativo:
            marca.ativo = ativo
            marca.save(user=self.request.user)
            self.auditar(
                'marca_ativada' if ativo else 'marca_desativada',
                objeto=marca,
                descricao=f'Marca {marca.nome}',
                motivo=entrada.validated_data.get('motivo', ''),
            )
        return Response(self._detalhe(marca))

    @extend_schema(request=CatalogoMotivoOpcionalSerializer, responses=CatalogoMarcaSerializer)
    @action(detail=True, methods=['post'])
    def ativar(self, request, pk=None):
        return self._alterar_situacao(True)

    @extend_schema(request=CatalogoMotivoOpcionalSerializer, responses=CatalogoMarcaSerializer)
    @action(detail=True, methods=['post'])
    def desativar(self, request, pk=None):
        return self._alterar_situacao(False)

    @extend_schema(responses=CatalogoIconeMarcaSerializer(many=True))
    @action(detail=False, methods=['get'], pagination_class=None)
    def icones(self, request):
        opcoes = [{'valor': valor, 'rotulo': rotulo} for valor, rotulo in Marca.ICONE_CHOICES]
        return Response(CatalogoIconeMarcaSerializer(opcoes, many=True).data)
