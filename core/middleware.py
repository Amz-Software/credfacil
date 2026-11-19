"""Login obrigatório por padrão no backoffice.

Toda rota exige usuário autenticado, exceto as listadas aqui. Assim uma view
nova nasce protegida mesmo que alguém esqueça o mixin/decorator; liberar uma
página pública passa a ser uma decisão explícita neste arquivo.
"""
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse

# Rotas com autenticação própria (JWT no DRF, login do admin) ou arquivos.
PREFIXOS_PUBLICOS = (
    '/api/',
    '/admin/',
    settings.STATIC_URL,
    settings.MEDIA_URL,
)

# Páginas abertas de propósito: login/recuperação de senha, consulta de
# pagamentos do cliente final e captura de foto pelo celular (link com UUID).
ROTAS_PUBLICAS = frozenset({
    'accounts:login',
    'accounts:logout',
    'accounts:buscar_lojas',
    'accounts:password_reset',
    'accounts:password_reset_done',
    'accounts:password_reset_confirm',
    'accounts:password_reset_complete',
    'vendas:consulta_pagamentos',
    'vendas:pagamento_detail',
    'vendas:parcela_informar',
    'vendas:informar_todos_pagamentos',
    'foto-celular',
})


class LoginObrigatorioMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.user.is_authenticated:
            return None
        if request.path.startswith(PREFIXOS_PUBLICOS):
            return None
        if request.resolver_match.view_name in ROTAS_PUBLICAS:
            return None
        return redirect_to_login(request.get_full_path())


CAMINHO_HEALTHZ = '/healthz/'


class HealthCheckMiddleware:
    """Responde `/healthz/` antes de qualquer outro middleware.

    Usado pelo healthcheck do Docker (autoheal) e pelo deploy. Fica no topo da
    pilha para não depender de ALLOWED_HOSTS (o container chama 127.0.0.1),
    sessão, login ou banco: só confirma que o servidor ainda processa requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == CAMINHO_HEALTHZ:
            return JsonResponse({'status': 'ok'})
        return self.get_response(request)
