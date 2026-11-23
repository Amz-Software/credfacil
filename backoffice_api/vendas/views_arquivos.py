"""Documentos (upload e download autenticado) e PDFs da venda — mixin do `VendaViewSet`."""
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.renderers import BaseRenderer, JSONRenderer

from .entradas import DocumentosVendaSerializer, validar_entrada
from .pdfs import TIPOS_CARNE, contexto_carne, contexto_contrato, contexto_nota, renderizar_pdf
from .regras import CAMPOS_DOCUMENTO, garantir_venda_ativa
from .serializers import VendaDetalheSerializer
from .servicos_documentos import abrir_documento, salvar_documentos

TAGS = ['bo-vendas']
ACOES_DE_ARQUIVO = {'arquivo', 'nota_pdf', 'carne_pdf', 'contrato_pdf'}
RESPOSTA_PDF = {(200, 'application/pdf'): OpenApiTypes.BINARY}


class RenderizadorArquivo(BaseRenderer):
    """Aceita `Accept: application/pdf`/`image/*` nas rotas de arquivo; erros continuam em JSON."""

    media_type = '*/*'
    format = 'arquivo'
    charset = None
    render_style = 'binary'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, (dict, list)):
            resposta = (renderer_context or {}).get('response')
            if resposta is not None:
                resposta['Content-Type'] = 'application/json'
            return JSONRenderer().render(data)
        return data


def resposta_pdf(conteudo: bytes, nome: str) -> HttpResponse:
    resposta = HttpResponse(conteudo, content_type='application/pdf')
    resposta['Content-Disposition'] = f'inline; filename="{nome}"'
    resposta['Cache-Control'] = 'private, no-store'
    return resposta


class DocumentosVendaMixin:
    def get_renderers(self):
        if getattr(self, 'action', None) in ACOES_DE_ARQUIVO:
            return [JSONRenderer(), RenderizadorArquivo()]
        return super().get_renderers()

    @extend_schema(
        tags=TAGS,
        summary='Enviar documentos da venda',
        request={'multipart/form-data': DocumentosVendaSerializer},
        responses=VendaDetalheSerializer,
    )
    @action(detail=True, methods=['post'], url_path='documentos', parser_classes=[MultiPartParser, FormParser])
    def documentos(self, request, pk=None):
        venda = self.get_object()
        garantir_venda_ativa(venda)
        entrada = validar_entrada(DocumentosVendaSerializer, request.data, {'venda': venda})
        campos = salvar_documentos(venda, entrada, request.user)
        self.auditar('venda_documentos_enviados', objeto=venda, dados={'campos': campos})
        return self.resposta_detalhe(venda.pk)

    @extend_schema(
        tags=TAGS,
        summary='Baixar documento da venda',
        parameters=[OpenApiParameter('campo', str, OpenApiParameter.PATH, enum=list(CAMPOS_DOCUMENTO))],
        responses={(200, '*/*'): OpenApiTypes.BINARY},
    )
    @action(
        detail=True, methods=['get'],
        url_path=r'arquivos/(?P<campo>documento_assinado|foto_cliente|imagem_imei)',
    )
    def arquivo(self, request, pk=None, campo=None):
        venda = self.get_object()
        resposta = abrir_documento(venda, campo)
        self.auditar('venda_documento_acessado', objeto=venda, dados={'campo': campo})
        return resposta

    def _gerar_pdf(self, documento: str, contexto_de, nome: str, **dados) -> HttpResponse:
        venda = self.get_object()
        conteudo = renderizar_pdf(f'{documento}.html', contexto_de(venda))
        self.auditar('venda_pdf_gerado', objeto=venda, dados={'documento': documento, **dados})
        return resposta_pdf(conteudo, nome.format(numero=venda.pk))

    @extend_schema(tags=TAGS, summary='Nota da venda (PDF)', responses=RESPOSTA_PDF)
    def nota_pdf(self, request, pk=None):
        return self._gerar_pdf('nota', contexto_nota, 'nota_venda_{numero}.pdf')

    @extend_schema(
        tags=TAGS,
        summary='Carnê ou promissória da venda (PDF)',
        parameters=[OpenApiParameter('tipo', str, enum=list(TIPOS_CARNE), default='carne')],
        responses=RESPOSTA_PDF,
    )
    def carne_pdf(self, request, pk=None):
        tipo = (request.query_params.get('tipo') or 'carne').strip().lower()
        if tipo not in TIPOS_CARNE:
            raise ValidationError({'tipo': ['Use carne ou promissoria.']})
        return self._gerar_pdf(
            'carne', lambda venda: contexto_carne(venda, tipo), f'{tipo}_venda_{{numero}}.pdf', tipo=tipo,
        )

    @extend_schema(tags=TAGS, summary='Contrato da venda (PDF)', responses=RESPOSTA_PDF)
    def contrato_pdf(self, request, pk=None):
        return self._gerar_pdf('contrato', contexto_contrato, 'contrato_venda_{numero}.pdf')
