"""Usuários: criação e edição com as regras de concessão, escopo e campos protegidos."""
from django.contrib.auth import get_user_model

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario

from .base import SENHA_NOVA, URL_USUARIOS, AdministracaoTestCase, criar_grupo, permissao, url_usuario

User = get_user_model()
GESTAO = ('accounts.view_user', 'accounts.add_user', 'accounts.change_user', 'vendas.view_cliente')


class CriacaoDeUsuarioTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.vendedor = criar_grupo('VENDEDOR', 'vendas.view_cliente')
        cls.admin = criar_grupo('ADMINISTRADOR', 'vendas.view_cliente', 'vendas.delete_venda')

    def setUp(self):
        self.gestor = criar_usuario('gestor', permissoes=GESTAO, lojas=(self.loja_a,))
        self.cliente = cliente_logado(self.gestor)

    def _corpo(self, **extra) -> dict:
        corpo = {'nome': 'João', 'sobrenome': 'Silva', 'email': 'Joao@Exemplo.com', 'senha': SENHA_NOVA,
                 'lojas': [self.loja_a.pk]}
        return {**corpo, **extra}

    def test_criar_exige_add_user(self):
        cliente = cliente_logado(criar_usuario('so_ver', permissoes=('accounts.view_user',), lojas=(self.loja_a,)))
        self.assertErro(cliente.post(URL_USUARIOS, self._corpo(), format='json'), 403, 'proibido')

    def test_criar_com_grupo_e_loja_gera_usuario_e_audita(self):
        corpo = self._corpo(grupos=[self.vendedor.pk], loja_principal=self.loja_a.pk)
        resposta = self.cliente.post(URL_USUARIOS, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        user = User.objects.get(pk=resposta.json()['id'])
        self.assertEqual((user.username, user.email), ('joao.silva', 'joao@exemplo.com'))
        self.assertTrue(user.check_password(SENHA_NOVA))
        self.assertEqual(list(user.lojas.all()), [self.loja_a])
        self.assertEqual(list(user.groups.all()), [self.vendedor])
        self.assertEqual(self.assertAuditado('usuario_criado', user).dados['grupos'], ['VENDEDOR'])

    def test_nunca_grava_superusuario_nem_staff(self):
        corpo = self._corpo(is_superuser=True, is_staff=True, superusuario=True, staff=True)
        resposta = self.cliente.post(URL_USUARIOS, corpo, format='json')
        user = User.objects.get(pk=resposta.json()['id'])
        self.assertFalse(user.is_superuser or user.is_staff)

    def test_senha_fraca_e_duplicados_recebem_400(self):
        self.assertErro(self.cliente.post(URL_USUARIOS, self._corpo(senha='123456'), format='json'), 400,
                        'validacao', 'senha')
        email = self._corpo(email=self.gestor.email.upper())
        self.assertErro(self.cliente.post(URL_USUARIOS, email, format='json'), 400, 'validacao', 'email')
        usuario = self._corpo(usuario='GESTOR')
        self.assertErro(self.cliente.post(URL_USUARIOS, usuario, format='json'), 400, 'validacao', 'usuario')

    def test_username_gerado_nao_colide(self):
        criar_usuario('joao.silva')
        resposta = self.cliente.post(URL_USUARIOS, self._corpo(), format='json')
        self.assertEqual(resposta.json()['usuario'], 'joao.silva2')

    def test_nao_concede_grupo_ou_permissao_que_nao_possui(self):
        grupo = self.cliente.post(URL_USUARIOS, self._corpo(grupos=[self.admin.pk]), format='json')
        self.assertErro(grupo, 403, 'proibido', 'grupos')
        direta = self._corpo(permissoes=[permissao('vendas.delete_venda').pk])
        self.assertErro(self.cliente.post(URL_USUARIOS, direta, format='json'), 403, 'proibido', 'permissoes')
        self.assertFalse(User.objects.filter(email='joao@exemplo.com').exists())

    def test_concede_acesso_ao_backoffice_que_possui(self):
        corpo = self._corpo(permissoes=[permissao('backoffice_api.acessar_backoffice').pk])
        resposta = self.cliente.post(URL_USUARIOS, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertTrue(resposta.json()['acesso_backoffice'])

    def test_lojas_so_do_escopo(self):
        fora = self.cliente.post(URL_USUARIOS, self._corpo(lojas=[self.loja_b.pk]), format='json')
        self.assertErro(fora, 403, 'proibido', 'lojas')
        principal = self.cliente.post(URL_USUARIOS, self._corpo(loja_principal=self.loja_b.pk), format='json')
        self.assertErro(principal, 403, 'proibido', 'loja_principal')
        sem_loja = self.cliente.post(URL_USUARIOS, self._corpo(lojas=[]), format='json')
        self.assertErro(sem_loja, 400, 'validacao', 'lojas')

    def test_superusuario_concede_qualquer_coisa(self):
        cliente = cliente_logado(criar_usuario('root', superuser=True))
        corpo = self._corpo(grupos=[self.admin.pk], lojas=[self.loja_b.pk])
        self.assertEqual(cliente.post(URL_USUARIOS, corpo, format='json').status_code, 201)


class EdicaoDeUsuarioTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.admin = criar_grupo('ADMINISTRADOR', 'vendas.view_cliente', 'vendas.delete_venda')
        cls.vendedor = criar_grupo('VENDEDOR', 'vendas.view_cliente')

    def setUp(self):
        self.gestor = criar_usuario('gestor', permissoes=GESTAO, lojas=(self.loja_a,))
        self.cliente = cliente_logado(self.gestor)
        self.alvo = criar_usuario('alvo', lojas=(self.loja_a, self.loja_b))

    def test_editar_dados_e_auditar_diferencas(self):
        corpo = {'nome': 'Novo', 'email': 'novo@exemplo.com', 'grupos': [self.vendedor.pk]}
        resposta = self.cliente.patch(url_usuario(self.alvo), corpo, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.alvo.refresh_from_db()
        self.assertEqual((self.alvo.first_name, self.alvo.email), ('Novo', 'novo@exemplo.com'))
        dados = self.assertAuditado('usuario_alterado', self.alvo).dados
        self.assertEqual(dados['grupos'], {'antes': [], 'depois': ['VENDEDOR']})

    def test_preserva_lojas_fora_do_escopo(self):
        resposta = self.cliente.patch(url_usuario(self.alvo), {'lojas': []}, format='json')
        self.assertEqual(resposta.json()['lojas'], [])
        self.assertEqual(list(self.alvo.lojas.all()), [self.loja_b])

    def test_campos_protegidos_sao_ignorados(self):
        self.cliente.patch(url_usuario(self.alvo), {'is_superuser': True, 'is_staff': True}, format='json')
        self.alvo.refresh_from_db()
        self.assertFalse(self.alvo.is_superuser or self.alvo.is_staff)

    def test_nao_edita_a_si_mesmo(self):
        erro = self.assertErro(self.cliente.patch(url_usuario(self.gestor), {'nome': 'X'}, format='json'), 403,
                               'proibido')
        self.assertIn('Meu perfil', erro['mensagem'])

    def test_nao_edita_quem_tem_mais_acesso_mesmo_inativo(self):
        self.alvo.groups.add(self.admin)
        self.alvo.is_active = False
        self.alvo.save()
        self.assertErro(self.cliente.patch(url_usuario(self.alvo), {'nome': 'X'}, format='json'), 403, 'proibido')
        self.assertErro(self.cliente.post(url_usuario(self.alvo, 'redefinir-senha')), 403, 'proibido')

    def test_nao_edita_staff_sem_ser_staff(self):
        self.alvo.is_staff = True
        self.alvo.save()
        self.assertErro(self.cliente.patch(url_usuario(self.alvo), {'nome': 'X'}, format='json'), 403, 'proibido')

    def test_nao_concede_grupo_que_nao_possui(self):
        resposta = self.cliente.patch(url_usuario(self.alvo), {'grupos': [self.admin.pk]}, format='json')
        self.assertErro(resposta, 403, 'proibido', 'grupos')
        self.assertFalse(self.alvo.groups.exists())

    def test_put_nao_existe_e_sem_permissao_recebe_403(self):
        self.assertErro(self.cliente.put(url_usuario(self.alvo), {}, format='json'), 405, 'metodo_nao_permitido')
        so_ver = cliente_logado(criar_usuario('so_ver', permissoes=('accounts.view_user',), lojas=(self.loja_a,)))
        self.assertErro(so_ver.patch(url_usuario(self.alvo), {'nome': 'X'}, format='json'), 403, 'proibido')
