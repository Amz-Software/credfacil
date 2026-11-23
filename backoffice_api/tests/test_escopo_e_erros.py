"""Escopo de lojas, permissões declaradas e contrato de erro do backoffice."""
from django.test import TestCase, override_settings

from .fabricas import cliente_logado, criar_loja, criar_usuario


@override_settings(ROOT_URLCONF='backoffice_api.tests.urls_teste')
class EscopoDeLojasTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Loja A')
        self.loja_b = criar_loja('Loja B')
        self.loja_c = criar_loja('Loja C')

    def test_usuario_comum_ve_so_as_proprias_lojas(self):
        user = criar_usuario('comum', lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/').json(), [self.loja_a.pk])
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA=str(self.loja_a.pk)).json(), [self.loja_a.pk])

    def test_usuario_comum_pedindo_outra_loja_recebe_403(self):
        user = criar_usuario('comum', lojas=(self.loja_a,))
        resposta = cliente_logado(user).get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA=str(self.loja_b.pk))
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'proibido')

    def test_gerente_ve_lojas_gerenciadas(self):
        user = criar_usuario('gerente', lojas=(self.loja_a,), gerente_de=(self.loja_c,))
        cliente = cliente_logado(user)
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/').json(), sorted([self.loja_a.pk, self.loja_c.pk]))
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA=str(self.loja_c.pk)).json(), [self.loja_c.pk])
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA=str(self.loja_b.pk)).status_code, 403)

    def test_administrador_com_permissao_global_ve_todas(self):
        user = criar_usuario('admin', permissoes=('vendas.can_view_all_stores',))
        cliente = cliente_logado(user)
        todas = sorted([self.loja_a.pk, self.loja_b.pk, self.loja_c.pk])
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA='todas').json(), todas)
        self.assertEqual(cliente.get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA=str(self.loja_b.pk)).json(), [self.loja_b.pk])

    def test_valor_invalido_no_cabecalho_recebe_400(self):
        user = criar_usuario('comum', lojas=(self.loja_a,))
        resposta = cliente_logado(user).get('/api/bo/v1/teste/escopo/', HTTP_X_LOJA='abc')
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'validacao')


@override_settings(ROOT_URLCONF='backoffice_api.tests.urls_teste')
class PermissoesDeclaradasTests(TestCase):
    def test_sem_permissao_exigida_recebe_403_no_contrato(self):
        cliente = cliente_logado(criar_usuario('semperm'))
        resposta = cliente.get('/api/bo/v1/teste/protegida/')
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'proibido')

    def test_com_permissao_exigida_passa(self):
        cliente = cliente_logado(criar_usuario('comperm', permissoes=('vendas.view_cliente',)))
        self.assertEqual(cliente.get('/api/bo/v1/teste/protegida/').status_code, 200)

    def test_view_sem_declaracao_e_negada_ate_para_quem_tem_acesso(self):
        cliente = cliente_logado(criar_usuario('qualquer', permissoes=('vendas.view_cliente',)))
        self.assertEqual(cliente.get('/api/bo/v1/teste/sem-declaracao/').status_code, 403)

    def test_anonimo_recebe_401_no_contrato(self):
        from rest_framework.test import APIClient

        resposta = APIClient().get('/api/bo/v1/teste/protegida/')
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta.json()['erro']['codigo'], 'nao_autenticado')


@override_settings(ROOT_URLCONF='backoffice_api.tests.urls_teste')
class ContratoDeErroTests(TestCase):
    def setUp(self):
        self.cliente = cliente_logado(criar_usuario('erros'))

    def test_404_no_contrato(self):
        resposta = self.cliente.get('/api/bo/v1/teste/erro/?tipo=404')
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.json(), {
            'erro': {'codigo': 'nao_encontrado', 'mensagem': 'Registro não encontrado.', 'campos': {}}
        })

    def test_erro_de_negocio_vira_422(self):
        resposta = self.cliente.get('/api/bo/v1/teste/erro/?tipo=negocio')
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()['erro']['codigo'], 'regra_de_negocio')
        self.assertEqual(resposta.json()['erro']['mensagem'], 'Marca sem parcelamento cadastrado.')

    def test_erro_inesperado_vira_500_sem_detalhes_internos(self):
        with self.assertLogs('backoffice_api.nucleo.erros', level='ERROR'):
            resposta = self.cliente.get('/api/bo/v1/teste/erro/')
        self.assertEqual(resposta.status_code, 500)
        self.assertEqual(resposta.json()['erro']['codigo'], 'erro_interno')
        self.assertNotIn('falha inesperada', resposta.content.decode())
