import os

from core import asgiref_patch

# Antes de tudo: cancelar um request preso não pode travar o event loop
# (incidente de 2026-11-12). Ver core/asgiref_patch.py.
asgiref_patch.aplicar()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.core.asgi import get_asgi_application
from notificacao.routing import websocket_urlpatterns
from notificacao.jwt_middleware import JwtAuthMiddlewareStack
from core.seguranca import origens_websocket

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    # Origem: como o AllowedHostsOriginValidator (ALLOWED_HOSTS), mais as
    # origens do CORS (a SPA do vendedor abre o WebSocket de outro domínio).
    # Autenticação: sessão/cookie (AuthMiddlewareStack) e, com `?token=<access>`
    # válido, o usuário do JWT (JwtAuthMiddlewareStack).
    "websocket": OriginValidator(
        AuthMiddlewareStack(
            JwtAuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
        origens_websocket(),
    ),
})
