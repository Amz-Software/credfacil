import os

from core import asgiref_patch

# Antes de tudo: cancelar um request preso não pode travar o event loop
# (incidente de 2026-11-12). Ver core/asgiref_patch.py.
asgiref_patch.aplicar()

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from notificacao.routing import websocket_urlpatterns
from notificacao.jwt_middleware import JwtAuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    # Keep existing session/cookie auth via AuthMiddlewareStack, but wrap
    # the URLRouter with JwtAuthMiddlewareStack so a valid `?token=` query
    # parameter will override the authenticated user for WebSocket
    # connections (preserving current behavior when token is absent).
    "websocket": AuthMiddlewareStack(
        JwtAuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
