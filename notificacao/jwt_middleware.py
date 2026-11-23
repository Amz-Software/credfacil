"""Autenticação JWT do WebSocket (`?token=<access>` na URL).

A SPA do vendedor não tem cookie de sessão no domínio da API: abre
`/ws/notifications/?token=<access token>`. Este middleware fica dentro do
`AuthMiddlewareStack`; com um token válido troca `scope['user']` pelo dono do
token, e sem token (ou com token inválido) deixa a autenticação por sessão como
estava.

Só vale token do tipo `access`, assinado, dentro da validade e de usuário ativo:
um refresh token (7 dias) não abre WebSocket.
"""
from urllib.parse import parse_qs
import logging

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

PREFIXO_BEARER = "bearer "


def _token_da_query_string(scope) -> str | None:
    bruto = scope.get("query_string", b"")
    texto = bruto.decode("utf-8", "ignore") if isinstance(bruto, bytes) else str(bruto)
    token = (parse_qs(texto).get("token") or [None])[0]
    if not token:
        return None
    token = token.strip()
    if token.lower().startswith(PREFIXO_BEARER):
        token = token[len(PREFIXO_BEARER):].strip()
    return token or None


def _usuario_do_token(token: str):
    """Usuário ativo dono do access token, ou None (token inválido, expirado, de outro tipo)."""
    # Import tardio: o módulo é importado pelo core/asgi.py antes do registro de apps.
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.settings import api_settings
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        # Confere assinatura, validade e o claim token_type == "access".
        validado = AccessToken(token)
    except TokenError as erro:
        logger.debug("JwtAuthMiddleware: token recusado: %s", erro)
        return None

    user_id = validado.get(api_settings.USER_ID_CLAIM)
    if user_id is None:
        return None
    usuario = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
    if usuario is None or not usuario.is_active:
        logger.debug("JwtAuthMiddleware: usuário %s inexistente ou inativo", user_id)
        return None
    return usuario


class JwtAuthMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":
            token = _token_da_query_string(scope)
            if token:
                usuario = await sync_to_async(_usuario_do_token)(token)
                if usuario is not None:
                    scope["user"] = usuario
        return await self.inner(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
