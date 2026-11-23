"""Sessão do backoffice: autenticação por cookie com expiração por inatividade.

Só vale a sessão criada pelo login do backoffice (marcada com `bo_login_em`);
a sessão das telas Django antigas não dá acesso à API nova.
"""
import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest
from rest_framework import exceptions
from rest_framework.authentication import SessionAuthentication

CHAVE_LOGIN_EM = 'bo_login_em'
CHAVE_ULTIMO_ACESSO = 'bo_ultimo_acesso'
CHAVE_TROCAR_SENHA = 'bo_trocar_senha'
# Grava o último acesso no máximo uma vez por minuto (evita escrever a sessão a cada requisição).
INTERVALO_ATUALIZACAO_S = 60


def iniciar_sessao_backoffice(request: HttpRequest, *, senha_fraca: bool) -> None:
    agora = int(time.time())
    request.session[CHAVE_LOGIN_EM] = agora
    request.session[CHAVE_ULTIMO_ACESSO] = agora
    request.session[CHAVE_TROCAR_SENHA] = senha_fraca
    request.session.set_expiry(settings.BACKOFFICE_SESSAO_MAXIMA_HORAS * 3600)


def expira_em(request: HttpRequest) -> int | None:
    """Timestamp (s) do limite absoluto da sessão do backoffice."""
    login_em = request.session.get(CHAVE_LOGIN_EM)
    if not login_em:
        return None
    return int(login_em) + settings.BACKOFFICE_SESSAO_MAXIMA_HORAS * 3600


class SessaoBackofficeAuthentication(SessionAuthentication):
    """Sessão do Django + CSRF + inatividade/limite absoluto do backoffice."""

    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is None:
            return None
        sessao = request._request.session
        login_em = sessao.get(CHAVE_LOGIN_EM)
        if not login_em:
            return None
        agora = int(time.time())
        ultimo = int(sessao.get(CHAVE_ULTIMO_ACESSO, login_em))
        inatividade = settings.BACKOFFICE_SESSAO_INATIVIDADE_MIN * 60
        maxima = settings.BACKOFFICE_SESSAO_MAXIMA_HORAS * 3600
        if agora - ultimo > inatividade or agora - int(login_em) > maxima:
            logout(request._request)
            raise exceptions.AuthenticationFailed('Sua sessão expirou. Entre novamente.')
        if agora - ultimo >= INTERVALO_ATUALIZACAO_S:
            sessao[CHAVE_ULTIMO_ACESSO] = agora
        return resultado

    def authenticate_header(self, request) -> str:
        # Com cabeçalho definido, o DRF responde 401 (e não 403) para "não autenticado".
        return 'Session'
