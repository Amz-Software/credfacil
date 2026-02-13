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
            raw_qs = scope.get("query_string", b"")
            # ensure query_string is a str (scope may provide bytes)
            if isinstance(raw_qs, bytes):
                try:
                    query_string = raw_qs.decode()
                except Exception:
                    query_string = raw_qs.decode("utf-8", "ignore")
            else:
                query_string = str(raw_qs)

            logger.debug("JwtAuthMiddleware: incoming websocket path=%s", scope.get("path"))
            print("JwtAuthMiddleware: incoming websocket path=", scope.get("path"))
            logger.debug("JwtAuthMiddleware: raw query_string=%s", query_string)
            print("JwtAuthMiddleware: raw query_string=", query_string)
            qs = parse_qs(query_string)
            token = qs.get("token", [None])[0]
            logger.debug("JwtAuthMiddleware: extracted token (pre-normalize)=%s type=%s", token, type(token))
            print("JwtAuthMiddleware: extracted token (pre-normalize)=", token, "type=", type(token))
            if token:
                # normalize token: decode bytes, ensure str, strip whitespace
                if isinstance(token, bytes):
                    try:
                        token = token.decode()
                    except Exception:
                        token = token.decode("utf-8", "ignore")

                token = str(token).strip() if token is not None else None
                if token and token.lower().startswith("bearer "):
                    token = token.split(" ", 1)[1]
                    logger.debug("JwtAuthMiddleware: stripped Bearer prefix")
                    print("JwtAuthMiddleware: stripped Bearer prefix, token=", token)
                logger.debug("JwtAuthMiddleware: normalized token type=%s", type(token))
                print("JwtAuthMiddleware: normalized token=", token, "type=", type(token))

                # Import lazily to avoid touching Django app registry at module import time.
                try:
                    from rest_framework_simplejwt.backends import TokenBackend
                    from django.contrib.auth import get_user_model
                except Exception as exc:
                    logger.exception("Failed importing JWT backend or user model: %s", exc)
                    print("JwtAuthMiddleware: import error for TokenBackend/get_user_model:", exc)
                else:
                    try:
                        # Build TokenBackend using simplejwt api_settings where possible
                        from rest_framework_simplejwt.settings import api_settings as jwt_api_settings

                        algorithm = None
                        # Prefer explicit setting in SIMPLE_JWT, fall back to api_settings
                        try:
                            algorithm = settings.SIMPLE_JWT.get("ALGORITHM") if isinstance(settings.SIMPLE_JWT, dict) else None
                        except Exception:
                            algorithm = None
                        if not algorithm:
                            algorithm = getattr(jwt_api_settings, "ALGORITHM", "HS256")

                        # Determine signing and verifying keys, ensure they are strings
                        signing_key = None
                        verifying_key = None
                        try:
                            signing_key = settings.SIMPLE_JWT.get("SIGNING_KEY") if isinstance(settings.SIMPLE_JWT, dict) else None
                        except Exception:
                            signing_key = None
                        if not signing_key:
                            signing_key = getattr(jwt_api_settings, "SIGNING_KEY", None) or getattr(settings, "SECRET_KEY", None)
                        if not isinstance(signing_key, str) and signing_key is not None:
                            signing_key = str(signing_key)

                        try:
                            verifying_key = settings.SIMPLE_JWT.get("VERIFYING_KEY") if isinstance(settings.SIMPLE_JWT, dict) else None
                        except Exception:
                            verifying_key = None
                        if not verifying_key:
                            verifying_key = getattr(jwt_api_settings, "VERIFYING_KEY", None)
                        if not isinstance(verifying_key, str):
                            # ensure verifying_key is either a string or None
                            verifying_key = None

                        token_backend = TokenBackend(
                            algorithm=algorithm,
                            signing_key=signing_key,
                            verifying_key=verifying_key,
                        )
                        logger.debug("JwtAuthMiddleware: attempting to decode token")
                        print("JwtAuthMiddleware: attempting to decode token")
                        validated_data = token_backend.decode(token, verify=True)
                        logger.debug("JwtAuthMiddleware: validated_data=%s", validated_data)
                        print("JwtAuthMiddleware: validated_data=", validated_data)
                        user_id = validated_data.get("user_id")
                        if user_id:
                            User = get_user_model()
                            try:
                                user = await sync_to_async(User.objects.get)(id=user_id)
                                scope["user"] = user
                                logger.debug("JwtAuthMiddleware: scope['user'] set to user id=%s", user_id)
                                print("JwtAuthMiddleware: scope['user'] set to user id=", user_id)
                            except Exception as e:
                                logger.debug("User lookup failed for id=%s: %s", user_id, e)
                                print("JwtAuthMiddleware: user lookup failed for id=", user_id, "error=", e)
                    except Exception as e:
                        # Log decode/validation errors so they can be diagnosed instead of
                        # being silently swallowed (which causes anonymous user and immediate close).
                        logger.debug("JWT decode/validation failed: %s", e, exc_info=True)
                        print("JwtAuthMiddleware: JWT decode/validation failed:", e)

        return await self.inner(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)
