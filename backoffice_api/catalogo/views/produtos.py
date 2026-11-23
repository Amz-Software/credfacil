"""Produtos: lista, detalhe, criação, edição, ativar/desativar, simulação e PDF."""
import json

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response

from backoffice_api.nucleo.erros import ErroBackoffice
from produtos.models import Produto

from ..base import CatalogoAPIView, CatalogoViewSet, loja_escolhida, lojas_para_filtro
from ..filtros import ORDENACAO_PRODUTOS, filtrar_produtos, ler_busca, ler_id, ordenar
from ..pdf import gerar_pdf_produtos
from ..serializers import (
    CatalogoMotivoOpcionalSerializer,
    CatalogoProdutoDetalheSerializer,
    CatalogoProdutoEntradaSerializer,
    CatalogoProdutoListaSerializer,
    CatalogoSimulacaoEntradaSerializer,
    CatalogoSimulacaoSerializer,
)
from ..servicos import (
    PERMISSAO_VER_TODOS_PRODUTOS,
    marcas_visiveis,
    produtos_visiveis,
    simular_parcelas,
)

VER = 'produtos.view_produto'
CRIAR = 'produtos.add_produto'
ALTERAR = 'produtos.change_produto'
ATIVAR_DESATIVAR = 'produtos.delete_produto'
TAG = ['bo-catalogo']

PARAMETROS_LISTA = [
    OpenApiParameter('busca', OpenApiTypes.STR, description='Nome (contém) ou código exato.'),
    OpenApiParameter('marca', OpenApiTypes.INT),
    OpenApiParameter('ativo', OpenApiTypes.STR, enum=['sim', 'nao', 'todos'],
                     description='Só com produtos.view_all_produtos (padrão: todos); sem ela, só ativos.'),
    OpenApiParameter('ordenar', OpenApiTypes.STR, description='nome, codigo, valor, entrada_cliente, criado_em (- para decrescente).'),
]


def _produtos_da_requisicao(view):
    return produtos_visiveis(view.request.user, lojas_para_filtro(view)).select_related(
        'marca', 'tipo', 'criado_por', 'modificado_por'
    )


def _lista_filtrada(view):
    params = view.request.query_params
    pode_ver_inativos = view.request.user.has_perm(PERMISSAO_VER_TODOS_PRODUTOS)
    produtos = filtrar_produtos(_produtos_da_requisicao(view), params, pode_ver_inativos=pode_ver_inativos)
    return ordenar(produtos, params, ORDENACAO_PRODUTOS, padrao=('nome', 'pk'))


@extend_schema(tags=TAG)
class ProdutoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    CatalogoViewSet,
):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    permissoes = {
        'list': [VER],
        'retrieve': [VER],
        'simulacao': [VER],
        'create': [CRIAR],
        'partial_update': [ALTERAR],
        'ativar': [ATIVAR_DESATIVAR],
        'desativar': [ATIVAR_DESATIVAR],
    }

    def get_queryset(self):
        if self.action == 'list':
            return _lista_filtrada(self)
        return _produtos_da_requisicao(self)

    def get_serializer_class(self):
        if self.action == 'list':
            return CatalogoProdutoListaSerializer
        if self.action in ('create', 'partial_update'):
            return CatalogoProdutoEntradaSerializer
        return CatalogoProdutoDetalheSerializer

    def _contexto_entrada(self) -> dict:
        return {'request': self.request, 'marcas': marcas_visiveis(lojas_para_filtro(self))}

    def _detalhe(self, produto: Produto) -> dict:
        recarregado = Produto.objects.select_related('marca', 'tipo', 'criado_por', 'modificado_por').get(pk=produto.pk)
        return CatalogoProdutoDetalheSerializer(recarregado, context={'request': self.request}).data

    @extend_schema(parameters=PARAMETROS_LISTA)
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=CatalogoProdutoEntradaSerializer, responses={201: CatalogoProdutoDetalheSerializer})
    def create(self, request):
        entrada = CatalogoProdutoEntradaSerializer(data=request.data, context=self._contexto_entrada())
        entrada.is_valid(raise_exception=True)
        produto = entrada.save(loja=loja_escolhida(self), criado_por=request.user, modificado_por=request.user)
        return Response(self._detalhe(produto), status=status.HTTP_201_CREATED)

    @extend_schema(request=CatalogoProdutoEntradaSerializer, responses=CatalogoProdutoDetalheSerializer)
    def partial_update(self, request, pk=None):
        produto = self.get_object()
        entrada = CatalogoProdutoEntradaSerializer(produto, data=request.data, partial=True, context=self._contexto_entrada())
        entrada.is_valid(raise_exception=True)
        produto = entrada.save(modificado_por=request.user)
        return Response(self._detalhe(produto))

    def _alterar_situacao(self, ativo: bool) -> Response:
        produto = self.get_object()
        entrada = CatalogoMotivoOpcionalSerializer(data=self.request.data)
        entrada.is_valid(raise_exception=True)
        if produto.ativo != ativo:
            produto.ativo = ativo
            produto.save(user=self.request.user)
            self.auditar(
                'produto_ativado' if ativo else 'produto_desativado',
                objeto=produto,
                descricao=f'Produto {produto.nome}',
                motivo=entrada.validated_data.get('motivo', ''),
            )
        return Response(self._detalhe(produto))

    @extend_schema(request=CatalogoMotivoOpcionalSerializer, responses=CatalogoProdutoDetalheSerializer)
    @action(detail=True, methods=['post'])
    def ativar(self, request, pk=None):
        return self._alterar_situacao(True)

    @extend_schema(request=CatalogoMotivoOpcionalSerializer, responses=CatalogoProdutoDetalheSerializer)
    @action(detail=True, methods=['post'])
    def desativar(self, request, pk=None):
        return self._alterar_situacao(False)

    @extend_schema(
        parameters=[OpenApiParameter('entrada', OpenApiTypes.DECIMAL, description='Padrão: entrada mínima do produto.')],
        responses=CatalogoSimulacaoSerializer,
    )
    @action(detail=True, methods=['get'])
    def simulacao(self, request, pk=None):
        produto = self.get_object()
        entrada = CatalogoSimulacaoEntradaSerializer(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        valor_entrada = entrada.validated_data.get('entrada')
        if valor_entrada is not None and produto.valor is not None and valor_entrada > produto.valor:
            mensagem = 'A entrada não pode ser maior que o valor do produto.'
            raise ErroBackoffice(mensagem, campos={'entrada': [mensagem]})
        return Response(CatalogoSimulacaoSerializer(simular_parcelas(produto, valor_entrada)).data)


class PDFRenderer(BaseRenderer):
    """Permite `Accept: application/pdf`; erros continuam saindo em JSON."""

    media_type = 'application/pdf'
    format = 'pdf'
    charset = None
    render_style = 'binary'

    def render(self, data, accepted_media_type=None, renderer_context=None) -> bytes:
        if isinstance(data, bytes):
            return data
        return json.dumps(data, ensure_ascii=False).encode('utf-8')


@extend_schema(
    tags=TAG,
    parameters=PARAMETROS_LISTA,
    responses={(200, 'application/pdf'): OpenApiTypes.BINARY},
)
class ProdutoRelatorioPDFView(CatalogoAPIView):
    """Mesmo conteúdo e filtros da lista, no PDF da tela Django."""

    permissoes = {'GET': [VER]}
    renderer_classes = [JSONRenderer, PDFRenderer]

    def get(self, request):
        produtos = _lista_filtrada(self)
        marca_id = ler_id(request.query_params, 'marca')
        marca = marcas_visiveis(lojas_para_filtro(self)).filter(pk=marca_id).first() if marca_id else None
        pdf = gerar_pdf_produtos(produtos, busca=ler_busca(request.query_params), marca=marca)
        resposta = HttpResponse(pdf, content_type='application/pdf')
        resposta['Content-Disposition'] = 'inline; filename="produtos.pdf"'
        return resposta
