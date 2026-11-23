"""Pré-análise rápida: lista, detalhe, aprovar, reprovar, consulta Serasa, arquivos e relatório PDF."""
from django.db import transaction
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response

from backoffice_api.nucleo.erros import NAO_ENCONTRADO_RECURSO, PROIBIDO_ACESSO, ErroBackoffice
from backoffice_api.nucleo.permissoes import EmGrupo
from backoffice_api.nucleo.views import BackofficeAPIView, BackofficeReadOnlyViewSet
from vendas.models import PreAnaliseRapida
from vendas.services import ErroDeNegocio
from vendas.services.erros import NAO_ENCONTRADO

from ..arquivos import ARQUIVOS_PRE_ANALISE, responder_arquivo, validar_uploads
from ..filtros import filtrar_pre_analises, ordenar_pre_analises
from ..regras import (
    PERMISSAO_DECIDIR,
    PERMISSAO_VER,
    PERMISSAO_VER_TODAS,
    pode_gerenciar_serasa_pre_analise,
    permissao_gerenciar_serasa_pre_analise,
)
from ..relatorio import gerar_pdf_pre_analises, nome_do_arquivo
from ..serializers.entradas import CreditoMotivoSerializer, CreditoUploadEntradaSerializer
from ..serializers.pre_analises import CreditoPreAnaliseDetalheSerializer, CreditoPreAnaliseListaSerializer
from .base import TAG, MetodoAntesDaPermissaoMixin, NegociacaoSemAccept

STATUS_PENDENTE = 'P'
GRUPOS_RELATORIO = ('ANALISTA', 'ADMINISTRADOR')
RELACOES = ('loja', 'criado_por', 'analisado_por', 'consulta_serasa_anexada_por')
PARAMETROS_LISTA = [
    OpenApiParameter('busca', OpenApiTypes.STR, description='Nome ou CPF.'),
    OpenApiParameter('status', OpenApiTypes.STR, enum=['P', 'A', 'R']),
    OpenApiParameter('loja', OpenApiTypes.INT, many=True),
    OpenApiParameter('data_inicio', OpenApiTypes.DATE),
    OpenApiParameter('data_fim', OpenApiTypes.DATE),
    OpenApiParameter('finalizada', OpenApiTypes.STR, enum=['1', '0']),
    OpenApiParameter('ordenar', OpenApiTypes.STR, description='id, criado_em, nome_completo, status, data_decisao.'),
]
MSG_JA_DECIDIDA = 'Esta pré-análise já foi decidida.'
MSG_FINALIZADA = 'Esta análise já virou proposta. Anexe a consulta Serasa direto no cadastro do cliente.'


def _base_pre_analises():
    return PreAnaliseRapida.objects.select_related(*RELACOES)


@extend_schema(tags=[TAG])
class PreAnaliseViewSet(MetodoAntesDaPermissaoMixin, BackofficeReadOnlyViewSet):
    permissao_global_lojas = PERMISSAO_VER_TODAS
    lookup_value_regex = r'\d+'
    permissoes = {
        'list': [PERMISSAO_VER],
        'retrieve': [PERMISSAO_VER],
        'arquivo': [PERMISSAO_VER],
        'aprovar': [PERMISSAO_DECIDIR],
        'reprovar': [PERMISSAO_DECIDIR],
        'consulta_serasa': [permissao_gerenciar_serasa_pre_analise],
    }

    def get_queryset(self):
        return self.filtrar_por_lojas(_base_pre_analises(), 'loja')

    def get_serializer_class(self):
        return CreditoPreAnaliseListaSerializer if self.action == 'list' else CreditoPreAnaliseDetalheSerializer

    @extend_schema(parameters=PARAMETROS_LISTA)
    def list(self, request, *args, **kwargs):
        params = request.query_params
        qs = ordenar_pre_analises(filtrar_pre_analises(self.get_queryset(), params), params)
        pagina = self.paginate_queryset(qs)
        dados = CreditoPreAnaliseListaSerializer(pagina, many=True, context=self.get_serializer_context()).data
        return self.get_paginated_response(dados)

    def _detalhe(self, pre_id: int) -> Response:
        pre = self.get_queryset().get(pk=pre_id)
        return Response(CreditoPreAnaliseDetalheSerializer(pre, context=self.get_serializer_context()).data)

    def _pendente(self) -> PreAnaliseRapida:
        pre = self.get_object()
        if pre.status != STATUS_PENDENTE:
            raise ErroDeNegocio(MSG_JA_DECIDIDA)
        return pre

    @extend_schema(request=None, responses=CreditoPreAnaliseDetalheSerializer)
    @action(detail=True, methods=['post'])
    def aprovar(self, request, pk=None):
        pre = self._pendente()
        with transaction.atomic():
            pre.aprovar(user=request.user)
            self.auditar('pre_analise_aprovada', objeto=pre, dados={'status_anterior': STATUS_PENDENTE, 'status_novo': pre.status})
        return self._detalhe(pre.pk)

    @extend_schema(request=CreditoMotivoSerializer, responses=CreditoPreAnaliseDetalheSerializer)
    @action(detail=True, methods=['post'])
    def reprovar(self, request, pk=None):
        serializer = CreditoMotivoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        motivo = serializer.validated_data['motivo']
        pre = self._pendente()
        with transaction.atomic():
            pre.reprovar(user=request.user, motivo=motivo)
            self.auditar(
                'pre_analise_reprovada', objeto=pre, motivo=motivo,
                dados={'status_anterior': STATUS_PENDENTE, 'status_novo': pre.status},
            )
        return self._detalhe(pre.pk)

    @extend_schema(
        methods=['POST'],
        request={'multipart/form-data': CreditoUploadEntradaSerializer},
        responses=CreditoPreAnaliseDetalheSerializer,
        description='Anexa (ou substitui) a consulta Serasa. Campo `arquivo` (PDF/JPG/PNG/WEBP, até 10 MB).',
    )
    @extend_schema(methods=['DELETE'], request=None, responses=CreditoPreAnaliseDetalheSerializer)
    @action(detail=True, methods=['post', 'delete'], url_path='consulta-serasa')
    def consulta_serasa(self, request, pk=None):
        pre = self.get_object()
        if pre.finalizada:
            raise ErroDeNegocio(MSG_FINALIZADA)
        if request.method == 'DELETE':
            return self._remover_serasa(pre)
        enviado = request.FILES.get('arquivo') or request.FILES.get('consulta_serasa')
        serializer = CreditoUploadEntradaSerializer(data={'arquivo': enviado} if enviado else {})
        serializer.is_valid(raise_exception=True)
        arquivo = serializer.validated_data['arquivo']
        validar_uploads({'arquivo': arquivo})
        with transaction.atomic():
            pre.anexar_consulta_serasa(arquivo, user=request.user)
            self.auditar('pre_analise_serasa_anexada', objeto=pre)
        return self._detalhe(pre.pk)

    def _remover_serasa(self, pre: PreAnaliseRapida) -> Response:
        with transaction.atomic():
            if not pre.remover_consulta_serasa(user=self.request.user):
                raise ErroDeNegocio('Nenhuma consulta Serasa anexada nesta análise.', codigo=NAO_ENCONTRADO)
            self.auditar('pre_analise_serasa_removida', objeto=pre)
        return self._detalhe(pre.pk)

    @extend_schema(
        parameters=[OpenApiParameter('download', OpenApiTypes.STR, enum=['1'])],
        responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY},
        description='Entrega foto_rg_frente, foto_rg_verso ou consulta_serasa (esta só para quem gerencia o Serasa).',
    )
    @action(
        detail=True, methods=['get'], url_path=r'arquivos/(?P<campo>[a-z0-9_]+)', url_name='arquivo',
        content_negotiation_class=NegociacaoSemAccept,
    )
    def arquivo(self, request, pk=None, campo=None):
        definicao = ARQUIVOS_PRE_ANALISE.get(campo)
        if definicao is None:
            raise ErroBackoffice('Arquivo não encontrado.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
        pre = self.get_object()
        if definicao.serasa and not pode_gerenciar_serasa_pre_analise(request.user):
            raise ErroBackoffice('Você não pode ver a consulta Serasa.', codigo=PROIBIDO_ACESSO, status_http=403)
        resposta = responder_arquivo(getattr(pre, campo), download=request.query_params.get('download') == '1')
        self.auditar('documento_acessado', objeto=pre, dados={'campo': campo})
        return resposta


@extend_schema(
    tags=[TAG],
    parameters=PARAMETROS_LISTA[:-1],
    responses={(200, 'application/pdf'): OpenApiTypes.BINARY},
    description='Mesmo PDF da tela atual, com os mesmos filtros da lista. Só ANALISTA/ADMINISTRADOR.',
)
class RelatorioPreAnalisesView(MetodoAntesDaPermissaoMixin, BackofficeAPIView):
    permissao_global_lojas = PERMISSAO_VER_TODAS
    permissoes = {'GET': [EmGrupo(*GRUPOS_RELATORIO)]}
    content_negotiation_class = NegociacaoSemAccept

    def get(self, request):
        params = request.query_params
        qs = ordenar_pre_analises(filtrar_pre_analises(self.filtrar_por_lojas(_base_pre_analises(), 'loja'), params), params)
        pdf, total = gerar_pdf_pre_analises(qs, params)
        self.auditar('relatorio_pre_analises_gerado', dados={'filtros': params.dict(), 'total': total})
        resposta = HttpResponse(pdf, content_type='application/pdf')
        resposta['Content-Disposition'] = f'attachment; filename="{nome_do_arquivo()}"'
        resposta['Cache-Control'] = 'private, no-store'
        return resposta
