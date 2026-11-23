"""Contrato de erro da API do backoffice.

Toda resposta de erro tem o formato:
    {"erro": {"codigo": str, "mensagem": str, "campos": {campo: [mensagens]}}}
"""
import logging

import sentry_sdk
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response

from vendas.services.erros import NAO_ENCONTRADO, PROIBIDO, ErroDeNegocio

logger = logging.getLogger(__name__)

VALIDACAO = 'validacao'
NAO_AUTENTICADO = 'nao_autenticado'
PROIBIDO_ACESSO = 'proibido'
NAO_ENCONTRADO_RECURSO = 'nao_encontrado'
CONFLITO = 'conflito'
REGRA_DE_NEGOCIO = 'regra_de_negocio'
LIMITE_EXCEDIDO = 'limite_excedido'
METODO_NAO_PERMITIDO = 'metodo_nao_permitido'
TROCA_SENHA_OBRIGATORIA = 'troca_senha_obrigatoria'
ERRO_INTERNO = 'erro_interno'


class ErroBackoffice(exceptions.APIException):
    """Erro com código do contrato; use nas views quando nenhum outro servir."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = 'Não foi possível concluir a operação.'

    def __init__(self, mensagem: str, *, codigo: str = VALIDACAO, status_http: int = 400, campos: dict | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.status_code = status_http
        self.campos = campos or {}


def corpo_erro(codigo: str, mensagem: str, campos: dict | None = None) -> dict:
    return {"erro": {"codigo": codigo, "mensagem": mensagem, "campos": campos or {}}}


def _normalizar_campos(detalhe) -> tuple[str, dict]:
    """Converte o `detail` de uma ValidationError do DRF em (mensagem, campos)."""
    if isinstance(detalhe, list):
        mensagens = [str(m) for m in detalhe]
        return (mensagens[0] if mensagens else 'Dados inválidos.'), {}
    if not isinstance(detalhe, dict):
        return str(detalhe), {}
    campos: dict[str, list[str]] = {}
    gerais: list[str] = []
    for campo, erros in detalhe.items():
        lista = erros if isinstance(erros, list) else [erros]
        textos = [str(e) for e in lista]
        if campo in ('non_field_errors', '__all__'):
            gerais.extend(textos)
        else:
            campos[str(campo)] = textos
    mensagem = gerais[0] if gerais else 'Revise os campos destacados.'
    return mensagem, campos


def tratar_excecao(exc, context) -> Response:
    """Exception handler usado só pelas views do backoffice."""
    if isinstance(exc, ErroBackoffice):
        return Response(corpo_erro(exc.codigo, str(exc.detail), exc.campos), status=exc.status_code)

    if isinstance(exc, ErroDeNegocio):
        if exc.codigo == PROIBIDO:
            return Response(corpo_erro(PROIBIDO_ACESSO, exc.mensagem), status=403)
        if exc.codigo == NAO_ENCONTRADO:
            return Response(corpo_erro(NAO_ENCONTRADO_RECURSO, exc.mensagem), status=404)
        return Response(corpo_erro(REGRA_DE_NEGOCIO, exc.mensagem), status=422)

    if isinstance(exc, exceptions.ValidationError):
        mensagem, campos = _normalizar_campos(exc.detail)
        return Response(corpo_erro(VALIDACAO, mensagem, campos), status=400)

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, 'message_dict'):
            mensagem, campos = _normalizar_campos(exc.message_dict)
        else:
            mensagem, campos = _normalizar_campos(exc.messages)
        return Response(corpo_erro(VALIDACAO, mensagem, campos), status=400)

    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        mensagem = str(exc.detail) if exc.detail else ''
        if not mensagem or 'credentials were not provided' in mensagem.lower() or 'não foram fornecidas' in mensagem.lower():
            mensagem = 'Faça login para continuar.'
        return Response(corpo_erro(NAO_AUTENTICADO, mensagem), status=401)

    if isinstance(exc, (exceptions.PermissionDenied, DjangoPermissionDenied)):
        codigo = getattr(exc, 'codigo', PROIBIDO_ACESSO)
        detalhe = getattr(exc, 'detail', None) or str(exc)
        mensagem = str(detalhe)
        if not mensagem or 'permission to perform' in mensagem.lower() or 'permissão para executar' in mensagem.lower():
            mensagem = 'Você não tem permissão para fazer isso.'
        return Response(corpo_erro(codigo, mensagem), status=403)

    if isinstance(exc, (exceptions.NotFound, Http404)):
        return Response(corpo_erro(NAO_ENCONTRADO_RECURSO, 'Registro não encontrado.'), status=404)

    if isinstance(exc, exceptions.MethodNotAllowed):
        return Response(corpo_erro(METODO_NAO_PERMITIDO, 'Operação não permitida.'), status=405)

    if isinstance(exc, exceptions.Throttled):
        espera = f' Tente de novo em {int(exc.wait)} segundos.' if exc.wait else ''
        return Response(corpo_erro(LIMITE_EXCEDIDO, 'Muitas requisições.' + espera), status=429)

    if isinstance(exc, exceptions.ParseError):
        return Response(corpo_erro(VALIDACAO, 'Não foi possível ler os dados enviados.'), status=400)

    if isinstance(exc, exceptions.UnsupportedMediaType):
        return Response(corpo_erro(VALIDACAO, 'Formato de envio não suportado.'), status=415)

    if isinstance(exc, exceptions.APIException):
        return Response(corpo_erro(VALIDACAO, str(exc.detail)), status=exc.status_code)

    view = context.get('view')
    logger.exception('Erro inesperado na API do backoffice (%s)', view.__class__.__name__ if view else '-')
    sentry_sdk.capture_exception(exc)
    return Response(
        corpo_erro(ERRO_INTERNO, 'Ocorreu um erro inesperado. Tente novamente em instantes.'),
        status=500,
    )
