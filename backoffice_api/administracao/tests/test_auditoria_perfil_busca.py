"""Auditoria (consulta e ações), meu perfil e provedor de busca global."""
from datetime import timedelta

from django.utils import timezone

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import SENHA_FORTE, cliente_logado, criar_loja, criar_usuario

from .base import URL, AdministracaoTestCase, ids

URL_AUDITORIA = f'{URL}/auditoria/'
URL_PERFIL = f'{URL}/perfil/'
URL_BUSCA = f'{URL}/busca/'


class AuditoriaTests(AdministracaoTestCase):
    def setUp(self):
        self.user = criar_usuario('auditor', permissoes=('backoffice_api.ver_auditoria',))
        self.cliente = cliente_logado(self.user)  # grava 'login'
        self.antigo = RegistroAuditoria.objects.create(usuario_nome='fulano', acao='usuario_desativado',
                                                       objeto_tipo='accounts.user', objeto_id='7', motivo='Saiu')
        RegistroAuditoria.objects.filter(pk=self.antigo.pk).update(criado_em=timezone.now() - timedelta(days=10))

    def test_sem_permissao_recebe_403(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_AUDITORIA), 403, 'proibido')

    def test_filtros(self):
        self.assertEqual(ids(self.cliente.get(URL_AUDITORIA, {'acao': 'usuario_desativado'})), {self.antigo.pk})
        objeto = {'objeto_tipo': 'accounts.user', 'objeto_id': '7'}
        self.assertEqual(ids(self.cliente.get(URL_AUDITORIA, objeto)), {self.antigo.pk})
        self.assertEqual(ids(self.cliente.get(URL_AUDITORIA, {'busca': 'saiu'})), {self.antigo.pk})
        hoje = timezone.localdate().isoformat()
        recentes = self.cliente.get(URL_AUDITORIA, {'data_inicio': hoje, 'usuario': self.user.pk}).json()['results']
        self.assertEqual([r['acao'] for r in recentes], ['login'])
        self.assertErro(self.cliente.get(URL_AUDITORIA, {'data_fim': '31/12/2026'}), 400, 'validacao', 'data_fim')

    def test_acoes_distintas_e_sem_post(self):
        self.assertEqual(self.cliente.get(f'{URL_AUDITORIA}acoes/').json()['acoes'], ['login', 'usuario_desativado'])
        self.assertErro(self.cliente.post(URL_AUDITORIA, {}), 405, 'metodo_nao_permitido')


class PerfilTests(AdministracaoTestCase):
    def setUp(self):
        self.user = criar_usuario('eu')
        self.cliente = cliente_logado(self.user)

    def test_ver_e_editar_nome_auditado(self):
        self.assertEqual(self.cliente.get(URL_PERFIL).json()['usuario'], 'eu')
        resposta = self.cliente.patch(URL_PERFIL, {'nome': 'Eduardo', 'is_superuser': True}, format='json')
        self.assertEqual(resposta.json()['nome'], 'Eduardo')
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)
        self.assertAuditado('perfil_alterado', self.user)

    def test_trocar_email_exige_senha_atual(self):
        sem_senha = self.cliente.patch(URL_PERFIL, {'email': 'novo@exemplo.com'}, format='json')
        self.assertErro(sem_senha, 400, 'validacao', 'senha_atual')
        com_senha = self.cliente.patch(URL_PERFIL, {'email': 'novo@exemplo.com', 'senha_atual': SENHA_FORTE},
                                       format='json')
        self.assertEqual(com_senha.json()['email'], 'novo@exemplo.com')

    def test_email_duplicado_e_put(self):
        criar_usuario('outro')
        corpo = {'email': 'outro@teste.local', 'senha_atual': SENHA_FORTE}
        self.assertErro(self.cliente.patch(URL_PERFIL, corpo, format='json'), 400, 'validacao', 'email')
        self.assertErro(self.cliente.put(URL_PERFIL, {}, format='json'), 405, 'metodo_nao_permitido')


class BuscaTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        for indice in range(10):
            criar_usuario(f'maria{indice}', lojas=(cls.loja_a,))
        cls.de_b = criar_usuario('mariab', lojas=(cls.loja_b,))

    def test_sem_permissao_recebe_403(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_BUSCA, {'termo': 'ma'}), 403, 'proibido')

    def test_busca_limitada_ao_escopo_e_a_oito(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=('accounts.view_user',), lojas=(self.loja_a,)))
        resultados = cliente.get(URL_BUSCA, {'termo': 'maria'}).json()['resultados']
        self.assertEqual(len(resultados), 8)
        self.assertNotIn(self.de_b.pk, {r['id'] for r in resultados})
        self.assertEqual(resultados[0]['tipo'], 'usuario')
        self.assertEqual(cliente.get(URL_BUSCA, {'termo': 'm'}).json()['resultados'], [])
