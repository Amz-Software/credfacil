"""Apoio aos testes da administração."""
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings

from backoffice_api.models import RegistroAuditoria

URL = '/api/bo/v1/administracao'
URL_USUARIOS = f'{URL}/usuarios/'
HASH_RAPIDO = ['django.contrib.auth.hashers.MD5PasswordHasher']
SENHA_NOVA = 'Outra@Senha2026x'


def permissao(codigo: str) -> Permission:
    app_label, codename = codigo.split('.', 1)
    return Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()


def criar_grupo(nome: str, *codigos: str) -> Group:
    grupo = Group.objects.create(name=nome)
    grupo.permissions.set([permissao(c) for c in codigos])
    return grupo


def url_usuario(user, acao: str = '') -> str:
    return f'{URL_USUARIOS}{user.pk}/' + (f'{acao}/' if acao else '')


@override_settings(PASSWORD_HASHERS=HASH_RAPIDO)
class AdministracaoTestCase(TestCase):
    def assertErro(self, resposta, status: int, codigo: str, campo: str | None = None):
        self.assertEqual(resposta.status_code, status, resposta.content)
        erro = resposta.json()['erro']
        self.assertEqual(erro['codigo'], codigo)
        if campo:
            self.assertIn(campo, erro['campos'])
        return erro

    def assertAuditado(self, acao: str, objeto) -> RegistroAuditoria:
        registro = RegistroAuditoria.objects.filter(
            acao=acao, objeto_tipo=objeto._meta.label_lower, objeto_id=str(objeto.pk)
        ).first()
        self.assertIsNotNone(registro, f'auditoria "{acao}" não gravada')
        return registro


def ids(resposta) -> set[int]:
    return {item['id'] for item in resposta.json()['results']}
