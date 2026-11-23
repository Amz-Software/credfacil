"""Usuários: desativar, reativar e redefinir senha (auditados)."""
from django.contrib.auth.password_validation import validate_password

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario

from .base import AdministracaoTestCase, url_usuario

GESTAO = ('accounts.view_user', 'accounts.change_user', 'accounts.delete_user')


class AcoesDeUsuarioTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')

    def setUp(self):
        self.gestor = criar_usuario('gestor', permissoes=GESTAO, lojas=(self.loja_a,))
        self.cliente = cliente_logado(self.gestor)
        self.alvo = criar_usuario('alvo', lojas=(self.loja_a,))

    def test_desativar_e_reativar_auditados(self):
        resposta = self.cliente.post(url_usuario(self.alvo, 'desativar'), {'motivo': 'Desligado'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.alvo.refresh_from_db()
        self.assertFalse(self.alvo.is_active)
        self.assertEqual(self.assertAuditado('usuario_desativado', self.alvo).motivo, 'Desligado')
        self.assertTrue(self.cliente.post(url_usuario(self.alvo, 'reativar')).json()['ativo'])
        self.assertAuditado('usuario_reativado', self.alvo)

    def test_desativar_exige_delete_user(self):
        cliente = cliente_logado(criar_usuario('ed', permissoes=('accounts.view_user', 'accounts.change_user'),
                                               lojas=(self.loja_a,)))
        self.assertErro(cliente.post(url_usuario(self.alvo, 'desativar')), 403, 'proibido')

    def test_get_em_acoes_responde_405(self):
        self.assertErro(self.cliente.get(url_usuario(self.alvo, 'desativar')), 405, 'metodo_nao_permitido')
        self.assertErro(self.cliente.get(url_usuario(self.alvo, 'redefinir-senha')), 405, 'metodo_nao_permitido')
        self.alvo.refresh_from_db()
        self.assertTrue(self.alvo.is_active)

    def test_usuario_de_outra_loja_responde_404(self):
        outro = criar_usuario('outro', lojas=(self.loja_b,))
        self.assertErro(self.cliente.post(url_usuario(outro, 'desativar')), 404, 'nao_encontrado')

    def test_nao_desativa_a_si_mesmo(self):
        self.assertErro(self.cliente.post(url_usuario(self.gestor, 'desativar')), 403, 'proibido')

    def test_redefinir_senha_devolve_senha_forte_uma_vez_e_audita_sem_ela(self):
        resposta = self.cliente.post(url_usuario(self.alvo, 'redefinir-senha'), {'motivo': 'Esqueceu'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta['Cache-Control'], 'no-store')
        senha = resposta.json()['senha_temporaria']
        self.alvo.refresh_from_db()
        self.assertTrue(self.alvo.check_password(senha))
        validate_password(senha, self.alvo)
        registro = self.assertAuditado('senha_redefinida', self.alvo)
        self.assertNotIn(senha, str(registro.dados) + registro.motivo + registro.descricao)
        self.assertEqual(RegistroAuditoria.objects.filter(acao='senha_redefinida').count(), 1)

    def test_redefinir_senha_exige_change_user(self):
        cliente = cliente_logado(criar_usuario('so_ver', permissoes=('accounts.view_user',), lojas=(self.loja_a,)))
        self.assertErro(cliente.post(url_usuario(self.alvo, 'redefinir-senha')), 403, 'proibido')
