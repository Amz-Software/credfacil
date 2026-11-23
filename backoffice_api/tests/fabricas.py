"""Fábricas de dados para os testes da API do backoffice."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from vendas.models import Loja

SENHA_FORTE = 'Senha@Forte2026'
URL_CSRF = '/api/bo/v1/auth/csrf/'
URL_LOGIN = '/api/bo/v1/auth/login/'


def criar_loja(nome: str = 'Loja A') -> Loja:
    return Loja.objects.create(nome=nome)


def _permissao(codigo: str) -> Permission:
    app_label, codename = codigo.split('.', 1)
    return Permission.objects.get(content_type__app_label=app_label, codename=codename)


def criar_usuario(
    username: str,
    *,
    permissoes: tuple[str, ...] = (),
    grupos: tuple[str, ...] = (),
    lojas: tuple[Loja, ...] = (),
    gerente_de: tuple[Loja, ...] = (),
    acesso_backoffice: bool = True,
    superuser: bool = False,
    senha: str = SENHA_FORTE,
    ativo: bool = True,
):
    User = get_user_model()
    user = User.objects.create_user(
        username=username,
        email=f'{username}@teste.local',
        password=senha,
        first_name=username.capitalize(),
        is_superuser=superuser,
        is_active=ativo,
    )
    codigos = list(permissoes) + (['backoffice_api.acessar_backoffice'] if acesso_backoffice else [])
    user.user_permissions.add(*[_permissao(c) for c in codigos])
    for nome in grupos:
        grupo, _ = Group.objects.get_or_create(name=nome)
        user.groups.add(grupo)
    for loja in lojas:
        loja.usuarios.add(user)
    for loja in gerente_de:
        loja.gerentes.add(user)
    return user


def cliente_logado(user, senha: str = SENHA_FORTE) -> APIClient:
    """APIClient com sessão do backoffice criada pelo endpoint de login (com CSRF)."""
    cliente = APIClient(enforce_csrf_checks=True)
    cliente.get(URL_CSRF)
    token = cliente.cookies['csrftoken'].value
    resposta = cliente.post(
        URL_LOGIN, {'usuario': user.username, 'senha': senha}, format='json', HTTP_X_CSRFTOKEN=token
    )
    assert resposta.status_code == 200, resposta.content
    cliente.credentials(HTTP_X_CSRFTOKEN=cliente.cookies['csrftoken'].value)
    return cliente
