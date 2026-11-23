"""Login, sessão, troca de senha e bloqueio por tentativas do backoffice."""
import time

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from backoffice_api.models import RegistroAuditoria
from backoffice_api.nucleo.sessao import CHAVE_ULTIMO_ACESSO

from .fabricas import SENHA_FORTE, URL_CSRF, URL_LOGIN, cliente_logado, criar_loja, criar_usuario

URL_ME = '/api/bo/v1/me/'
URL_LOGOUT = '/api/bo/v1/auth/logout/'
URL_SENHA = '/api/bo/v1/me/senha/'


def _cliente_com_csrf() -> tuple[APIClient, str]:
    cliente = APIClient(enforce_csrf_checks=True)
    cliente.get(URL_CSRF)
    return cliente, cliente.cookies['csrftoken'].value


def _login(cliente: APIClient, token: str, usuario: str, senha: str):
    return cliente.post(URL_LOGIN, {'usuario': usuario, 'senha': senha}, format='json', HTTP_X_CSRFTOKEN=token)


class LoginTests(TestCase):
    def test_login_valido_devolve_me_com_lojas_e_permissoes(self):
        loja = criar_loja('Centro')
        user = criar_usuario('analista', grupos=('ANALISTA',), lojas=(loja,), permissoes=('vendas.view_cliente',))
        cliente, token = _cliente_com_csrf()
        resposta = _login(cliente, token, 'analista', SENHA_FORTE)
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual(corpo['usuario'], 'analista')
        self.assertEqual(corpo['grupos'], ['ANALISTA'])
        self.assertIn('vendas.view_cliente', corpo['permissoes'])
        self.assertEqual(corpo['lojas'], [{'id': loja.pk, 'nome': 'Centro'}])
        self.assertFalse(corpo['deve_trocar_senha'])
        self.assertTrue(RegistroAuditoria.objects.filter(usuario=user, acao='login').exists())

    def test_login_sem_csrf_e_recusado(self):
        criar_usuario('analista')
        cliente = APIClient(enforce_csrf_checks=True)
        resposta = cliente.post(URL_LOGIN, {'usuario': 'analista', 'senha': SENHA_FORTE}, format='json')
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'csrf_invalido')

    def test_senha_errada_responde_401_generico_e_audita(self):
        criar_usuario('analista')
        cliente, token = _cliente_com_csrf()
        resposta = _login(cliente, token, 'analista', 'errada')
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json()['erro']['mensagem'], 'Usuário ou senha inválidos.')
        self.assertTrue(RegistroAuditoria.objects.filter(usuario_nome='analista', acao='login_falhou').exists())

    def test_usuario_inativo_responde_igual_a_senha_errada(self):
        criar_usuario('inativo', ativo=False)
        cliente, token = _cliente_com_csrf()
        resposta = _login(cliente, token, 'inativo', SENHA_FORTE)
        self.assertEqual(resposta.status_code, 401)

    def test_vendedor_sem_acesso_ao_backoffice_e_recusado(self):
        criar_usuario('vendedor', grupos=('VENDEDOR',), acesso_backoffice=False)
        cliente, token = _cliente_com_csrf()
        resposta = _login(cliente, token, 'vendedor', SENHA_FORTE)
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'proibido')
        self.assertEqual(cliente.get(URL_ME).status_code, 401)

    def test_jwt_nao_autentica_na_api_do_backoffice(self):
        from rest_framework_simplejwt.tokens import AccessToken

        user = criar_usuario('analista')
        cliente = APIClient()
        cliente.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        self.assertEqual(cliente.get(URL_ME).status_code, 401)

    def test_sessao_das_telas_antigas_nao_vale_na_api_nova(self):
        user = criar_usuario('analista')
        cliente = APIClient()
        cliente.force_login(user)
        self.assertEqual(cliente.get(URL_ME).status_code, 401)


class SessaoTests(TestCase):
    def test_logout_invalida_a_sessao_no_servidor(self):
        cliente = cliente_logado(criar_usuario('analista'))
        self.assertEqual(cliente.post(URL_LOGOUT).status_code, 204)
        self.assertEqual(cliente.get(URL_ME).status_code, 401)

    def test_sessao_expira_por_inatividade(self):
        cliente = cliente_logado(criar_usuario('analista'))
        sessao = cliente.session
        sessao[CHAVE_ULTIMO_ACESSO] = int(time.time()) - 31 * 60
        sessao.save()
        resposta = cliente.get(URL_ME)
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json()['erro']['mensagem'], 'Sua sessão expirou. Entre novamente.')


@override_settings(ROOT_URLCONF='backoffice_api.tests.urls_teste')
class SenhaForaDaPoliticaTests(TestCase):
    SENHA_FRACA = 'senhafraca'

    def setUp(self):
        self.user = criar_usuario('antigo', senha=self.SENHA_FRACA, permissoes=('vendas.view_cliente',))
        self.cliente = cliente_logado(self.user, senha=self.SENHA_FRACA)

    def test_login_com_senha_fraca_exige_troca(self):
        self.assertTrue(self.cliente.get(URL_ME).json()['deve_trocar_senha'])
        resposta = self.cliente.get('/api/bo/v1/teste/protegida/')
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'troca_senha_obrigatoria')

    def test_nova_senha_fraca_e_recusada_com_erro_no_campo(self):
        resposta = self.cliente.post(URL_SENHA, {
            'senha_atual': self.SENHA_FRACA, 'nova_senha': 'outrasenha1', 'confirmacao': 'outrasenha1',
        }, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('nova_senha', resposta.json()['erro']['campos'])

    def test_senha_atual_errada_e_recusada(self):
        resposta = self.cliente.post(URL_SENHA, {
            'senha_atual': 'nao-e-essa', 'nova_senha': SENHA_FORTE, 'confirmacao': SENHA_FORTE,
        }, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('senha_atual', resposta.json()['erro']['campos'])

    def test_troca_valida_libera_o_acesso_sem_novo_login(self):
        resposta = self.cliente.post(URL_SENHA, {
            'senha_atual': self.SENHA_FRACA, 'nova_senha': SENHA_FORTE, 'confirmacao': SENHA_FORTE,
        }, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.json()['deve_trocar_senha'])
        self.assertEqual(self.cliente.get('/api/bo/v1/teste/protegida/').status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(SENHA_FORTE))


@override_settings(AXES_ENABLED=True)
class BloqueioPorTentativasTests(TestCase):
    def test_bloqueia_apos_cinco_falhas_mesmo_com_senha_certa(self):
        criar_usuario('analista')
        cliente, token = _cliente_com_csrf()
        for _ in range(5):
            _login(cliente, token, 'analista', 'errada')
        resposta = _login(cliente, token, 'analista', SENHA_FORTE)
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(resposta.json()['erro']['codigo'], 'limite_excedido')


class SenhaForteValidatorTests(TestCase):
    def test_regras(self):
        from django.core.exceptions import ValidationError

        from accounts.validators import SenhaForteValidator

        validador = SenhaForteValidator()
        validador.validate('Senha@Forte2026')
        for fraca in ('senha@forte2026', 'SENHA@FORTE2026', 'Senha@Forte', 'SenhaForte2026'):
            with self.assertRaises(ValidationError):
                validador.validate(fraca)
