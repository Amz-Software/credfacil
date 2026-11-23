"""Mídia das mensagens (storage privado) pela API do backoffice.

Reaproveita a entrega das telas (`crm/web/midia.py::midia`): Range (206) para áudio e vídeo,
`?versao=miniatura`, `LogAcessoMidia` ao abrir o original (a miniatura não entra no log),
`nosniff`, SVG/HTML só como download e, com S3, redirect para URL assinada de 5 minutos.
A permissão é conferida aqui antes (`crm.acessar_crm`) e de novo pela view reaproveitada.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema

from crm.web.midia import midia as entregar_midia

from ..base import CrmAPIView
from ..permissoes import ACESSO
from . import TAGS


class MidiaView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(
        tags=TAGS, summary='Arquivo da mensagem (original ou miniatura)',
        parameters=[OpenApiParameter('versao', str, enum=['miniatura'], required=False,
                                     description='Miniatura JPEG (imagem, figurinha e vídeo), sem log de acesso.')],
        responses={
            (200, 'application/octet-stream'): OpenApiTypes.BINARY,
            (206, 'application/octet-stream'): OpenApiTypes.BINARY,
            302: None,
        },
    )
    def get(self, request, mensagem_id: int):
        return entregar_midia(request._request, mensagem_id=mensagem_id)
