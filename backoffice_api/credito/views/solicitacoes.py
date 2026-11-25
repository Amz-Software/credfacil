"""Fila de análise de crédito: lista, KPIs, detalhe, edição, arquivos e QR de instalação."""
import base64

from django.db import transaction
from django.db.models import Exists, OuterRef
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from api.views.solicitacoes_regras import gerar_qrcode_instalacao
from backoffice_api.nucleo.auditoria import ip_do_cliente
from backoffice_api.nucleo.erros import NAO_ENCONTRADO_RECURSO, PROIBIDO_ACESSO, ErroBackoffice
from backoffice_api.nucleo.permissoes import EmGrupo
from backoffice_api.nucleo.views import BackofficeViewSet
from vendas.models import AnaliseCreditoCliente, Cliente, ConsultaSerasaAcesso, Loja, PreAnaliseRapida
from vendas.services.kpis import contar_por_status

from ..arquivos import ARQUIVOS_SOLICITACAO, TIPO_SERASA, mime_pelos_bytes, responder_arquivo
from ..criacao import criar_solicitacao
from ..edicao import editar_solicitacao
from ..filtros import analises_para_kpis, filtrar_solicitacoes, ordenar_solicitacoes
from ..opcoes_edicao import opcoes_de_criacao, opcoes_de_edicao
from ..regras import (
    GRUPOS_CRIACAO,
    GRUPOS_OBSERVACAO,
    PERMISSAO_DECIDIR,
    PERMISSAO_VER,
    PERMISSAO_VER_TODAS,
    STATUS_APROVADO,
    pode_ver_serasa,
    permissao_ver_serasa,
)
from ..serializers.respostas import (
    CreditoEdicaoRespostaSerializer,
    CreditoKpisSerializer,
    CreditoOpcoesEdicaoSerializer,
    CreditoQrInstalacaoSerializer,
)
from ..serializers.solicitacao_detalhe import CreditoSolicitacaoDetalheSerializer
from ..serializers.solicitacao_lista import CreditoSolicitacaoListaSerializer
from .base import TAG, MetodoAntesDaPermissaoMixin, NegociacaoSemAccept
from .solicitacoes_acoes import AcoesDaSolicitacaoMixin

RELACOES_LISTA = (
    'loja',
    'analise_credito',
    'analise_credito__produto',
    'analise_credito__criado_por',
)
RELACOES_DETALHE = RELACOES_LISTA + (
    'contato_adicional',
    'informacao_pessoal',
    'comprovantes',
    'analise_credito__produto__marca',
    'analise_credito__imei',
    'analise_credito__aprovado_por',
    'analise_credito__numero_autenticador',
    'analise_credito__venda',
    'analise_credito__venda__vendedor',
)
PARAMETROS_FILA = [
    OpenApiParameter('busca', OpenApiTypes.STR, description='Nome ou CPF (com ou sem máscara).'),
    OpenApiParameter('loja', OpenApiTypes.INT, many=True, description='Uma ou mais lojas (?loja=1&loja=2 ou 1,2).'),
    OpenApiParameter('status', OpenApiTypes.STR, enum=['EA', 'A', 'R', 'C']),
    OpenApiParameter('status_app', OpenApiTypes.STR, enum=['P', 'C', 'I']),
    OpenApiParameter('data_inicio', OpenApiTypes.DATE),
    OpenApiParameter('data_fim', OpenApiTypes.DATE),
    OpenApiParameter('analise_online', OpenApiTypes.STR, enum=['1', '0']),
    OpenApiParameter('vendas_nao_finalizadas', OpenApiTypes.STR, enum=['1']),
    OpenApiParameter(
        'ordenar', OpenApiTypes.STR,
        description='id, nome, data_analise, status, loja ou produto (prefixo "-" = decrescente). '
                    'Padrão: em análise primeiro, a mais antiga no topo.',
    ),
]


def _data_uri(campo_arquivo) -> str | None:
    if not campo_arquivo or not getattr(campo_arquivo, 'name', ''):
        return None
    try:
        with campo_arquivo.open('rb') as arquivo:
            conteudo = arquivo.read()
    except (OSError, ValueError):
        return None
    mime = mime_pelos_bytes(conteudo[:16]) or 'image/png'
    return f'data:{mime};base64,{base64.b64encode(conteudo).decode()}'


_VEIO_DA_ANALISE_RAPIDA = Exists(PreAnaliseRapida.objects.filter(cliente_gerado=OuterRef('cliente')))


def _contadores(analises) -> dict:
    """Totais por status, geral e de aprovadas sem venda de um conjunto de análises."""
    por_status = contar_por_status(analises)
    return {
        'por_status': por_status,
        'total': sum(por_status.values()),
        'aprovadas_sem_venda': analises.filter(status=STATUS_APROVADO, venda__isnull=True).count(),
    }


@extend_schema(tags=[TAG])
class SolicitacaoViewSet(
    MetodoAntesDaPermissaoMixin,
    AcoesDaSolicitacaoMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    BackofficeViewSet,
):
    """Solicitações de crédito (id = id do cliente)."""

    permissao_global_lojas = PERMISSAO_VER_TODAS
    lookup_value_regex = r'\d+'
    permissoes = {
        'list': [PERMISSAO_VER],
        'retrieve': [PERMISSAO_VER],
        'kpis': [PERMISSAO_VER],
        'arquivo': [PERMISSAO_VER],
        'create': ['vendas.add_cliente', EmGrupo(*GRUPOS_CRIACAO)],
        'opcoes_criacao': ['vendas.add_cliente', EmGrupo(*GRUPOS_CRIACAO)],
        'partial_update': ['vendas.change_cliente'],
        'qr_instalacao': ['vendas.change_cliente'],
        'opcoes_edicao': ['vendas.change_cliente'],
        'aprovar': [PERMISSAO_DECIDIR],
        'reprovar': [PERMISSAO_DECIDIR],
        'cancelar': ['vendas.change_analisecreditocliente', PERMISSAO_DECIDIR],
        'observacoes': [EmGrupo(*GRUPOS_OBSERVACAO)],
        'status_app': ['vendas.change_cliente'],
        'instalar_app': ['vendas.change_cliente'],
        'confirmar_instalacao': [PERMISSAO_DECIDIR, EmGrupo('ANALISTA')],
        'confirmar_icloud': [PERMISSAO_DECIDIR, EmGrupo('ANALISTA')],
        'informar_imei': ['vendas.change_analisecreditocliente', EmGrupo('ANALISTA')],
        'gerar_venda': ['vendas.add_venda'],
        'log_consulta_serasa': [PERMISSAO_VER, permissao_ver_serasa],
    }

    def get_queryset(self):
        relacoes = RELACOES_LISTA if self.action == 'list' else RELACOES_DETALHE
        base = Cliente.objects.filter(analise_credito__isnull=False).select_related(*relacoes)
        return self.filtrar_por_lojas(base, 'loja')

    def get_serializer_class(self):
        return CreditoSolicitacaoListaSerializer if self.action == 'list' else CreditoSolicitacaoDetalheSerializer

    @extend_schema(parameters=PARAMETROS_FILA)
    def list(self, request, *args, **kwargs):
        params = request.query_params
        qs = ordenar_solicitacoes(filtrar_solicitacoes(self.get_queryset(), params), params)
        pagina = self.paginate_queryset(qs)
        dados = CreditoSolicitacaoListaSerializer(pagina, many=True, context=self.get_serializer_context()).data
        return self.get_paginated_response(dados)

    @extend_schema(
        parameters=[OpenApiParameter('loja', OpenApiTypes.INT, many=True)],
        responses=CreditoKpisSerializer,
    )
    @action(detail=False, methods=['get'])
    def kpis(self, request):
        analises = self.filtrar_por_lojas(analises_para_kpis(request.query_params), 'loja')
        return Response({
            **_contadores(analises),
            'online': _contadores(analises.filter(analise_online=True)),
            'analise_rapida': _contadores(analises.filter(_VEIO_DA_ANALISE_RAPIDA)),
            'status_opcoes': [{'codigo': c, 'rotulo': r} for c, r in AnaliseCreditoCliente.STATUS_CHOICES],
            'status_app_opcoes': [{'codigo': c, 'rotulo': r} for c, r in AnaliseCreditoCliente.STATUS_APP_CHOICES],
        })

    @extend_schema(
        request={'multipart/form-data': OpenApiTypes.OBJECT, 'application/json': OpenApiTypes.OBJECT},
        responses={201: CreditoEdicaoRespostaSerializer},
        description='Nova solicitação (analista/administrador), sempre na loja da CredFácil (IPIXX). '
                    'Mesmos campos da edição; documentos opcionais, em multipart (ver CONTRATO.md).',
    )
    def create(self, request, *args, **kwargs):
        with transaction.atomic():
            resultado = criar_solicitacao(request.user, request.data, request.FILES)
            cliente = resultado.cliente
            self.auditar('solicitacao_criada', objeto=cliente.analise_credito, dados={'solicitacao_id': cliente.pk})
        criado = Cliente.objects.select_related(*RELACOES_DETALHE).get(pk=cliente.pk)
        contexto = {**self.get_serializer_context(), 'aviso': resultado.aviso}
        return Response(CreditoEdicaoRespostaSerializer(criado, context=contexto).data, status=201)

    @extend_schema(responses=CreditoOpcoesEdicaoSerializer)
    @action(detail=False, methods=['get'], url_path='opcoes-criacao')
    def opcoes_criacao(self, request):
        return Response(opcoes_de_criacao(request.user))

    @extend_schema(
        request={'multipart/form-data': OpenApiTypes.OBJECT, 'application/json': OpenApiTypes.OBJECT},
        responses=CreditoEdicaoRespostaSerializer,
        description='Edição parcial: envie só os campos alterados (ver CONTRATO.md). Arquivos em multipart.',
    )
    def partial_update(self, request, *args, **kwargs):
        cliente = self.get_object()
        with transaction.atomic():
            resultado = editar_solicitacao(cliente, request.user, request.data, request.FILES)
            self.auditar(
                'solicitacao_editada',
                objeto=cliente.analise_credito,
                dados={'solicitacao_id': cliente.pk, 'campos': resultado.campos},
            )
        atualizado = self.get_queryset().get(pk=cliente.pk)
        contexto = {**self.get_serializer_context(), 'aviso': resultado.aviso}
        return Response(CreditoEdicaoRespostaSerializer(atualizado, context=contexto).data)

    @extend_schema(
        parameters=[OpenApiParameter('download', OpenApiTypes.STR, enum=['1'], description='Força o download.')],
        responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY},
        description='Entrega um comprovante. Campos: ' + ', '.join(ARQUIVOS_SOLICITACAO) + '.',
    )
    @action(
        detail=True, methods=['get'], url_path=r'arquivos/(?P<campo>[a-z0-9_]+)', url_name='arquivo',
        content_negotiation_class=NegociacaoSemAccept,
    )
    def arquivo(self, request, pk=None, campo=None):
        definicao = ARQUIVOS_SOLICITACAO.get(campo)
        if definicao is None:
            raise ErroBackoffice('Arquivo não encontrado.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
        cliente = self.get_object()
        if definicao.serasa and not pode_ver_serasa(request.user):
            raise ErroBackoffice('Você não pode ver a consulta Serasa.', codigo=PROIBIDO_ACESSO, status_http=403)
        analise = cliente.analise_credito
        origem = cliente.comprovantes if definicao.origem == 'comprovantes' else analise
        resposta = responder_arquivo(getattr(origem, campo), download=request.query_params.get('download') == '1')
        if definicao.serasa:
            self._registrar_acesso_serasa(cliente, TIPO_SERASA[campo])
        self.auditar('documento_acessado', objeto=analise, dados={'solicitacao_id': cliente.pk, 'campo': campo})
        return resposta

    @extend_schema(responses=CreditoQrInstalacaoSerializer)
    @action(detail=True, methods=['get'], url_path='qr-instalacao')
    def qr_instalacao(self, request, pk=None):
        cliente = self.get_object()
        qr_base64, codigo = gerar_qrcode_instalacao(cliente_id=cliente.pk, loja_id=cliente.loja_id)
        loja_credfacil = Loja.objects.filter(credfacil=True).first()
        return Response({
            'qr_instalacao': f'data:image/png;base64,{qr_base64}',
            'codigo_instalacao': codigo,
            'qr_aplicativo': _data_uri(loja_credfacil.qr_code_aplicativo) if loja_credfacil else None,
            'codigo_aplicativo': loja_credfacil.codigo_aplicativo if loja_credfacil else None,
        })

    @extend_schema(responses=CreditoOpcoesEdicaoSerializer)
    @action(detail=True, methods=['get'], url_path='opcoes-edicao')
    def opcoes_edicao(self, request, pk=None):
        return Response(opcoes_de_edicao(self.get_object(), request.user))

    def _registrar_acesso_serasa(self, cliente: Cliente, tipo: str) -> ConsultaSerasaAcesso:
        return ConsultaSerasaAcesso.objects.create(
            cliente=cliente,
            usuario=self.request.user,
            tipo=tipo,
            ip_address=ip_do_cliente(self.request),
            user_agent=(self.request.META.get('HTTP_USER_AGENT') or '')[:512],
        )
