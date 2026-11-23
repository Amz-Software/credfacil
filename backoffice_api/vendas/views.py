"""Vendas da API do backoffice: lista, detalhe, edição e ações (edição especial, troca, cancelamento)."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response

from vendas.models import Cliente

from ..nucleo.escopo import tem_acesso_global
from ..nucleo.permissoes import QualquerPermissao
from ..nucleo.views import BackofficeViewSet
from .consultas import (
    ORDENACAO_VENDAS,
    buscar_vendas,
    com_detalhes,
    filtrar_vendas,
    imeis_disponiveis,
    ler_inteiro,
    ordenar,
    vendas_anotadas,
)
from .entradas import (
    EdicaoEspecialVendaSerializer,
    EdicaoVendaSerializer,
    MotivoVendaSerializer,
    TrocaProdutoVendaSerializer,
    validar_entrada,
)
from .serializers import (
    ImeiDisponivelVendaSerializer,
    ItemVendaSerializer,
    OpcoesTrocaVendaSerializer,
    ResultadoBuscaVendaSerializer,
    VendaDetalheSerializer,
    VendaListaSerializer,
    resultado_de_busca,
)
from .servicos_acoes import cancelar_venda, produtos_para_troca, trocar_produto
from .servicos_edicao import editar_venda, editar_venda_especial
from .views_arquivos import TAGS, DocumentosVendaMixin

PERMISSAO_TODAS_AS_VENDAS = 'vendas.can_view_all_sales'
PERMISSAO_TODOS_OS_IMEIS = 'estoque.can_view_all_imei'
ACOES_COM_DETALHES = {'retrieve', 'nota_pdf', 'carne_pdf', 'contrato_pdf'}
LIMITE_BUSCA = 8
MINIMO_TERMO_BUSCA = 2

PARAMETROS_LISTA = [
    OpenApiParameter('busca', str, description='Número da venda, nome/CPF do cliente ou IMEI'),
    OpenApiParameter('cliente', str, description='Nome do cliente (contém)'),
    OpenApiParameter('numero', int, description='Número (id) da venda'),
    OpenApiParameter('loja', int, description='Loja (só para quem vê todas as vendas)'),
    OpenApiParameter('canceladas', str, enum=['true', 'false', 'todas'], description='Padrão: false'),
    OpenApiParameter('trocadas', bool),
    OpenApiParameter('origem', str, enum=['manual', 'analise']),
    OpenApiParameter('data_inicio', OpenApiTypes.DATE),
    OpenApiParameter('data_fim', OpenApiTypes.DATE),
    OpenApiParameter('ordenar', str, description='Campos: ' + ', '.join(sorted(ORDENACAO_VENDAS))),
]


@extend_schema_view(
    list=extend_schema(tags=TAGS, summary='Listar vendas', parameters=PARAMETROS_LISTA),
    retrieve=extend_schema(tags=TAGS, summary='Detalhe da venda', responses=VendaDetalheSerializer),
)
class VendaViewSet(DocumentosVendaMixin, BackofficeViewSet):
    serializer_class = VendaListaSerializer
    permissao_global_lojas = PERMISSAO_TODAS_AS_VENDAS
    lookup_value_regex = r'\d+'
    permissoes = {
        'list': ['vendas.view_venda'],
        'retrieve': ['vendas.view_venda'],
        'partial_update': ['vendas.change_venda'],
        'edicao_especial': ['vendas.can_edit_imei_valores_venda'],
        'opcoes_troca': ['vendas.change_venda'],
        'trocar_produto': ['vendas.change_venda'],
        'cancelar': ['vendas.delete_venda'],
        'documentos': ['vendas.change_venda'],
        'arquivo': ['vendas.view_venda'],
        'nota_pdf': ['vendas.view_venda'],
        'carne_pdf': ['vendas.view_venda'],
        'contrato_pdf': ['vendas.view_venda'],
        'busca': ['vendas.view_venda'],
        'imeis_disponiveis': [QualquerPermissao('vendas.change_venda', 'vendas.can_edit_imei_valores_venda')],
    }

    def initial(self, request, *args, **kwargs):
        # Método sem ação mapeada responde 405 (e não 403 das permissões declaradas).
        if request.method != 'OPTIONS' and request.method.lower() not in (self.action_map or {}):
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)

    def get_queryset(self):
        queryset = vendas_anotadas()
        if self.action in ACOES_COM_DETALHES:
            queryset = com_detalhes(queryset)
        return self.filtrar_por_lojas(queryset)

    def resposta_detalhe(self, pk: int, status: int = 200) -> Response:
        """Recarrega a venda (com itens, pagamentos e histórico) depois de uma alteração."""
        venda = com_detalhes(self.filtrar_por_lojas(vendas_anotadas())).get(pk=pk)
        return Response(VendaDetalheSerializer(venda, context={'request': self.request}).data, status=status)

    def _clientes_do_escopo(self):
        return self.filtrar_por_lojas(Cliente.objects.all())

    def list(self, request):
        pode_filtrar_loja = tem_acesso_global(request.user, self.permissao_global_lojas)
        queryset = filtrar_vendas(self.get_queryset(), request.query_params, pode_filtrar_loja=pode_filtrar_loja)
        queryset = ordenar(queryset, request.query_params.get('ordenar'), ORDENACAO_VENDAS, '-data_venda')
        pagina = self.paginate_queryset(queryset)
        return self.get_paginated_response(VendaListaSerializer(pagina, many=True, context={'request': request}).data)

    def retrieve(self, request, pk=None):
        return Response(VendaDetalheSerializer(self.get_object(), context={'request': request}).data)

    @extend_schema(tags=TAGS, summary='Editar venda', request=EdicaoVendaSerializer, responses=VendaDetalheSerializer)
    def partial_update(self, request, pk=None):
        venda = self.get_object()
        entrada = validar_entrada(EdicaoVendaSerializer, request.data)
        alteracoes = editar_venda(venda, entrada, request.user, clientes=self._clientes_do_escopo())
        if alteracoes:
            self.auditar('venda_editada', objeto=venda, dados=alteracoes)
        return self.resposta_detalhe(venda.pk)

    @extend_schema(tags=TAGS, summary='Edição especial (IMEI/produto/parcelas)', request=EdicaoEspecialVendaSerializer,
                   responses=VendaDetalheSerializer)
    @action(detail=True, methods=['post'], url_path='edicao-especial')
    def edicao_especial(self, request, pk=None):
        venda = self.get_object()
        entrada = validar_entrada(EdicaoEspecialVendaSerializer, request.data)
        alteracoes = editar_venda_especial(venda, entrada, request.user)
        self.auditar('venda_edicao_especial', objeto=venda, motivo=entrada['motivo'], dados=alteracoes)
        return self.resposta_detalhe(venda.pk)

    def _imeis_do_escopo(self):
        queryset = imeis_disponiveis()
        if self.request.user.has_perm(PERMISSAO_TODOS_OS_IMEIS):
            return queryset
        return self.filtrar_por_lojas(queryset)

    @extend_schema(tags=TAGS, summary='Opções para a troca de produto', responses=OpcoesTrocaVendaSerializer)
    @action(detail=True, methods=['get'], url_path='opcoes-troca')
    def opcoes_troca(self, request, pk=None):
        venda = self.get_object()
        produtos = [{'id': p.pk, 'nome': p.nome} for p in produtos_para_troca(venda)]
        itens = ItemVendaSerializer(venda.itens_venda.select_related('produto').order_by('pk'), many=True).data
        return Response({'itens': itens, 'produtos_disponiveis': produtos})

    @extend_schema(tags=TAGS, summary='Trocar produto da venda', request=TrocaProdutoVendaSerializer,
                   responses=VendaDetalheSerializer)
    @action(detail=True, methods=['post'], url_path='trocar-produto')
    def trocar_produto(self, request, pk=None):
        venda = self.get_object()
        entrada = validar_entrada(TrocaProdutoVendaSerializer, request.data)
        troca = trocar_produto(venda, entrada, request.user, imeis=self._imeis_do_escopo())
        self.auditar('venda_produto_trocado', objeto=venda, motivo=entrada['motivo'], dados=troca)
        return self.resposta_detalhe(venda.pk)

    @extend_schema(tags=TAGS, summary='Cancelar venda', request=MotivoVendaSerializer, responses=VendaDetalheSerializer)
    @action(detail=True, methods=['post'], url_path='cancelar')
    def cancelar(self, request, pk=None):
        venda = self.get_object()
        entrada = validar_entrada(MotivoVendaSerializer, request.data)
        cancelar_venda(venda, request.user)
        self.auditar('venda_cancelada', objeto=venda, motivo=entrada['motivo'])
        return self.resposta_detalhe(venda.pk)

    @extend_schema(
        tags=TAGS,
        summary='Busca global de vendas',
        parameters=[OpenApiParameter('termo', str, required=True, description='Número, nome/CPF do cliente ou IMEI')],
        responses=ResultadoBuscaVendaSerializer(many=True),
    )
    @action(detail=False, methods=['get'], url_path='busca')
    def busca(self, request):
        termo = (request.query_params.get('termo') or '').strip()
        if len(termo) < MINIMO_TERMO_BUSCA and not termo.isdigit():
            raise ValidationError({'termo': [f'Digite ao menos {MINIMO_TERMO_BUSCA} caracteres.']})
        vendas = buscar_vendas(self.get_queryset(), termo, LIMITE_BUSCA)
        return Response(ResultadoBuscaVendaSerializer([resultado_de_busca(v) for v in vendas], many=True).data)

    @extend_schema(
        tags=TAGS,
        summary='IMEIs disponíveis para a troca',
        parameters=[
            OpenApiParameter('produto', int, required=True),
            OpenApiParameter('venda', int, description='Restringe à loja desta venda'),
            OpenApiParameter('busca', str, description='Parte do IMEI'),
        ],
        responses=ImeiDisponivelVendaSerializer(many=True),
    )
    @action(detail=False, methods=['get'], url_path='imeis-disponiveis')
    def imeis_disponiveis(self, request):
        produto = ler_inteiro(request.query_params, 'produto')
        if produto is None:
            raise ValidationError({'produto': ['Informe o produto.']})
        queryset = self._imeis_do_escopo().filter(produto_id=produto)
        venda_id = ler_inteiro(request.query_params, 'venda')
        if venda_id is not None:
            venda = self.get_queryset().filter(pk=venda_id).first()
            if venda is None:
                raise ValidationError({'venda': ['Venda não encontrada.']})
            queryset = queryset.filter(loja_id=venda.loja_id)
        busca = (request.query_params.get('busca') or '').strip()
        if busca:
            queryset = queryset.filter(imei__icontains=busca)
        pagina = self.paginate_queryset(queryset)
        dados = [
            {
                'id': imei.pk, 'imei': imei.imei,
                'produto': {'id': imei.produto_id, 'nome': imei.produto.nome},
                'loja': {'id': imei.loja_id, 'nome': imei.loja.nome} if imei.loja else None,
            }
            for imei in pagina
        ]
        return self.get_paginated_response(ImeiDisponivelVendaSerializer(dados, many=True).data)
