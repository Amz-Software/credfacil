from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from django.conf import settings
import logging


logger = logging.getLogger(__name__)


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
            query_string = scope.get("query_string", b"").decode()
            qs = parse_qs(query_string)
            token = qs.get("token", [None])[0]
            if token:
                # strip common "Bearer " prefix if present
                if isinstance(token, str) and token.lower().startswith("bearer "):
                    token = token.split(" ", 1)[1]

                # Import lazily to avoid touching Django app registry at module import time.
                try:
                    from rest_framework_simplejwt.backends import TokenBackend
                    from django.contrib.auth import get_user_model
                except Exception as exc:
                    logger.exception("Failed importing JWT backend or user model: %s", exc)
                else:
                    try:
                        token_backend = TokenBackend(
                            algorithm=settings.SIMPLE_JWT.get("ALGORITHM", "HS256")
                        )
                        validated_data = token_backend.decode(token, verify=True)
                        user_id = validated_data.get("user_id")
                        if user_id:
                            User = get_user_model()
                            try:
                                user = await sync_to_async(User.objects.get)(id=user_id)
                                scope["user"] = user
                            except Exception as e:
                                logger.debug("User lookup failed for id=%s: %s", user_id, e)
                    except Exception as e:
                        # Log decode/validation errors so they can be diagnosed instead of
                        # being silently swallowed (which causes anonymous user and immediate close).
                        logger.debug("JWT decode/validation failed: %s", e, exc_info=True)

        return await self.inner(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
