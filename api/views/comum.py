"""Utilitários compartilhados pelas views da API."""
import logging

from rest_framework.response import Response

from vendas.services import ErroDeNegocio


logger = logging.getLogger(__name__)


ERRO_INESPERADO_VENDA = "Não foi possível salvar a venda. Tente novamente ou fale com o suporte."


def _resposta_de_erro(erro: ErroDeNegocio) -> Response:
    return Response({"detail": erro.mensagem}, status=erro.status_http)
