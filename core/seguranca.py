"""Respostas de segurança compartilhadas entre as telas e as APIs."""
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
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


# --------------------------------------------------------------------------
# Limite de tentativas por IP nas views Django públicas
# --------------------------------------------------------------------------
# As taxas são as mesmas do DRF (REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']),
# ex.: "20/min". O contador fica no cache padrão (por processo).
SEGUNDOS_POR_PERIODO = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
METODOS_LIMITADOS_PADRAO = ('POST',)


def ip_do_cliente(request: HttpRequest) -> str:
    """IP real atrás de `AXES_PROXY_COUNT` proxies (o último salto confiável do X-Forwarded-For).

    O primeiro endereço do X-Forwarded-For é escolhido pelo cliente; por isso
    conta-se a partir da direita, como o DRF faz com `NUM_PROXIES`.
    """
    proxies = int(getattr(settings, 'AXES_IPWARE_PROXY_COUNT', 0) or 0)
    encaminhado = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if proxies and encaminhado:
        enderecos = [e.strip() for e in encaminhado.split(',') if e.strip()]
        if enderecos:
            return enderecos[-min(proxies, len(enderecos))]
    return request.META.get('REMOTE_ADDR', '') or 'desconhecido'


def _taxa(escopo: str) -> tuple[int, int]:
    """(quantidade, janela em segundos) da taxa do escopo, ex.: '20/min' → (20, 60)."""
    taxa = settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][escopo]
    quantidade, periodo = taxa.split('/')
    return int(quantidade), SEGUNDOS_POR_PERIODO[periodo.strip()[0]]


def mensagem_limite_excedido() -> str:
    return 'Muitas tentativas seguidas. Aguarde um minuto e tente novamente.'


def _resposta_limite_excedido(request: HttpRequest, resposta_json: bool) -> HttpResponse:
    mensagem = mensagem_limite_excedido()
    if resposta_json:
        return JsonResponse({'error': mensagem, 'detail': mensagem}, status=429)
    messages.error(request, mensagem)
    return redirect(request.path)


def limite_excedido(escopo: str, request: HttpRequest) -> bool:
    """Conta a tentativa do IP no escopo e diz se passou da taxa."""
    quantidade, janela = _taxa(escopo)
    chave = f'limite:{escopo}:{ip_do_cliente(request)}'
    cache.add(chave, 0, timeout=janela)
    try:
        tentativas = cache.incr(chave)
    except ValueError:  # a chave expirou entre o add e o incr
        cache.set(chave, 1, timeout=janela)
        tentativas = 1
    return tentativas > quantidade


def limitar_por_ip(escopo: str, metodos: tuple[str, ...] = METODOS_LIMITADOS_PADRAO, resposta_json: bool = False):
    """Decorator de view: limita por IP as requisições `metodos` ao `escopo` ('publico', 'login').

    Ao passar do limite responde 429 em JSON (`resposta_json=True`) ou volta à
    própria página com a mensagem de erro (formulários).
    """
    def decorador(view):
        @wraps(view)
        def view_limitada(request: HttpRequest, *args, **kwargs):
            if request.method in metodos and limite_excedido(escopo, request):
                return _resposta_limite_excedido(request, resposta_json)
            return view(request, *args, **kwargs)
        return view_limitada
    return decorador


# --------------------------------------------------------------------------
# WebSocket: origens aceitas
# --------------------------------------------------------------------------
def origens_websocket() -> list[str]:
    """ALLOWED_HOSTS (telas Django) + origens do CORS (SPA do vendedor em outro domínio).

    Equivale ao `AllowedHostsOriginValidator` do Channels, mais as origens da SPA
    do vendedor, que abre o WebSocket a partir do próprio domínio.
    """
    hosts = list(settings.ALLOWED_HOSTS)
    if settings.DEBUG and not hosts:
        hosts = ['localhost', '127.0.0.1', '[::1]']
    return hosts + list(getattr(settings, 'CORS_ALLOWED_ORIGINS', []))
