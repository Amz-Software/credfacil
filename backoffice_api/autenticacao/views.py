"""Login, logout, usuário logado e troca de senha do backoffice."""
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import exceptions
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from core.seguranca import mensagem_bloqueio

from ..nucleo.auditoria import auditar
from ..nucleo.erros import LIMITE_EXCEDIDO, NAO_AUTENTICADO, ErroBackoffice, tratar_excecao
from ..nucleo.permissoes import PermissaoNegada, tem_acesso_backoffice
from ..nucleo.sessao import CHAVE_TROCAR_SENHA, iniciar_sessao_backoffice
from ..nucleo.views import BackofficeAPIView
from .serializers import LoginSerializer, TrocarSenhaSerializer, dados_me

MENSAGEM_CREDENCIAIS = 'Usuário ou senha inválidos.'
MENSAGEM_SEM_ACESSO = (
    'Seu usuário não tem acesso ao backoffice. Vendedores devem usar o aplicativo de vendas.'
)


def senha_atende_politica(senha: str, user) -> bool:
    try:
        validate_password(senha, user)
    except DjangoValidationError:
        return False
    return True


def exigir_csrf(request) -> None:
    """Confere o token CSRF mesmo em views sem autenticação (ex.: login)."""
    try:
        SessionAuthentication().enforce_csrf(request)
    except exceptions.PermissionDenied:
        raise PermissaoNegada(
            'A verificação de segurança expirou. Recarregue a página e tente de novo.',
            codigo='csrf_invalido',
        )


class _PublicaView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get_exception_handler(self):
        return tratar_excecao


class CsrfView(_PublicaView):
    """Grava o cookie `csrftoken`; a SPA chama antes do login."""

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        return Response({'ok': True})


class LoginView(_PublicaView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def post(self, request):
        exigir_csrf(request)
        entrada = LoginSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        usuario = entrada.validated_data['usuario']
        senha = entrada.validated_data['senha']

        user = authenticate(request._request, username=usuario, password=senha)
        if getattr(request._request, 'axes_locked_out', False):
            raise ErroBackoffice(mensagem_bloqueio(), codigo=LIMITE_EXCEDIDO, status_http=429)
        if user is None or not user.is_active:
            auditar(request, 'login_falhou', usuario_nome=usuario)
            raise ErroBackoffice(MENSAGEM_CREDENCIAIS, codigo=NAO_AUTENTICADO, status_http=401)
        if not tem_acesso_backoffice(user):
            auditar(request, 'login_negado', usuario=user)
            raise PermissaoNegada(MENSAGEM_SEM_ACESSO)

        senha_fraca = not senha_atende_politica(senha, user)
        login(request._request, user)
        iniciar_sessao_backoffice(request._request, senha_fraca=senha_fraca)
        auditar(request, 'login', usuario=user, dados={'senha_fora_da_politica': senha_fraca})
        return Response(dados_me(user, request))


class LogoutView(BackofficeAPIView):
    permissoes = {'POST': []}
    permite_com_troca_de_senha_pendente = True

    def post(self, request):
        auditar(request, 'logout')
        logout(request._request)
        return Response(status=204)


class MeView(BackofficeAPIView):
    permissoes = {'GET': []}
    permite_com_troca_de_senha_pendente = True

    def get(self, request):
        return Response(dados_me(request.user, request))


class TrocarSenhaView(BackofficeAPIView):
    permissoes = {'POST': []}
    permite_com_troca_de_senha_pendente = True

    def post(self, request):
        user = request.user
        entrada = TrocarSenhaSerializer(data=request.data, context={'user': user})
        entrada.is_valid(raise_exception=True)
        user.set_password(entrada.validated_data['nova_senha'])
        user.save(update_fields=['password'])
        update_session_auth_hash(request._request, user)
        request.session[CHAVE_TROCAR_SENHA] = False
        auditar(request, 'senha_alterada', objeto=user)
        return Response(dados_me(user, request))
