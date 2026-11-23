"""Respostas de segurança compartilhadas entre as telas e as APIs."""
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect


def mensagem_bloqueio() -> str:
    minutos = int(settings.AXES_COOLOFF_TIME.total_seconds() // 60)
    return f"Muitas tentativas de acesso. Aguarde {minutos} minutos e tente novamente."


def resposta_bloqueio_login(request: HttpRequest, credentials: dict | None = None) -> HttpResponse:
    """Resposta do django-axes quando o login está bloqueado por tentativas."""
    mensagem = mensagem_bloqueio()
    if request.path.startswith('/api/bo/'):
        return JsonResponse(
            {"erro": {"codigo": "limite_excedido", "mensagem": mensagem, "campos": {}}},
            status=429,
        )
    if request.path.startswith('/api/'):
        return JsonResponse({"detail": mensagem}, status=429)
    messages.error(request, mensagem)
    return redirect(settings.LOGIN_URL)
