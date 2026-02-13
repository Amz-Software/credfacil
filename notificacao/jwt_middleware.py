from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework_simplejwt.backends import TokenBackend


class JwtAuthMiddleware:
    """
    ASGI middleware that looks for a JWT in the WebSocket querystring
    (`?token=<access_token>`). If present and valid, it sets `scope['user']`
    to the authenticated user. If token is absent or invalid, it does
    nothing (leaving previous auth intact).

    This middleware is intended to be used inside `AuthMiddlewareStack`
    (so we can *override* session-based auth when a token is provided).
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Only inspect websocket connections
        if scope.get("type") == "websocket":
            try:
                query_string = scope.get("query_string", b"").decode()
                qs = parse_qs(query_string)
                token = qs.get("token", [None])[0]
                if token:
                    token_backend = TokenBackend(
                        algorithm=settings.SIMPLE_JWT.get("ALGORITHM", "HS256")
                    )
                    # decode verifies signature and returns payload
                    validated_data = token_backend.decode(token, verify=True)
                    user_id = validated_data.get("user_id") or validated_data.get("user_id")
                    if user_id:
                        User = get_user_model()
                        user = await sync_to_async(User.objects.get)(id=user_id)
                        scope["user"] = user
            except Exception:
                # If anything fails, silently continue and keep existing scope['user']
                pass

        return await self.inner(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
