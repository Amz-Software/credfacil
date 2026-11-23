"""Usuários: lista, filtros, escopo de lojas, superusuários e detalhe."""
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario

from .base import URL_USUARIOS, AdministracaoTestCase, criar_grupo, ids, url_usuario

VER = ('accounts.view_user',)


class ListaDeUsuariosTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.vendedores = criar_grupo('VENDEDOR', 'vendas.view_cliente')
        cls.ana = criar_usuario('ana', lojas=(cls.loja_a,), grupos=('VENDEDOR',))
        cls.bia = criar_usuario('bia', gerente_de=(cls.loja_a,))
        cls.caio = criar_usuario('caio', lojas=(cls.loja_b,))
        cls.dani = criar_usuario('dani', ativo=False, lojas=(cls.loja_a,))
        cls.sem_loja = criar_usuario('semloja')
        cls.root = criar_usuario('root', superuser=True, lojas=(cls.loja_a,))

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('semperm', lojas=(self.loja_a,)))
        self.assertErro(cliente.get(URL_USUARIOS), 403, 'proibido')

    def test_ve_so_usuarios_das_lojas_do_escopo_sem_superusuario_nem_si_mesmo(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=VER, lojas=(self.loja_a,)))
        resposta = cliente.get(URL_USUARIOS)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(ids(resposta), {self.ana.pk, self.bia.pk})
        item = next(u for u in resposta.json()['results'] if u['id'] == self.ana.pk)
        self.assertEqual(item['grupos'], ['VENDEDOR'])
        self.assertNotIn('password', item)

    def test_filtros(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(ids(cliente.get(URL_USUARIOS, {'ativo': 'nao'})), {self.dani.pk})
        self.assertEqual(ids(cliente.get(URL_USUARIOS, {'busca': 'ana@'})), {self.ana.pk})
        self.assertEqual(ids(cliente.get(URL_USUARIOS, {'grupo': self.vendedores.pk})), {self.ana.pk})
        self.assertEqual(ids(cliente.get(URL_USUARIOS, {'loja': self.loja_b.pk})), set())
        self.assertErro(cliente.get(URL_USUARIOS, {'ordenar': 'password'}), 400, 'validacao', 'ordenar')

    def test_loja_fora_do_escopo_no_cabecalho_recebe_403(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.get(URL_USUARIOS, HTTP_X_LOJA=str(self.loja_b.pk)), 403, 'proibido')

    def test_gerente_ve_usuarios_da_loja_gerenciada(self):
        cliente = cliente_logado(criar_usuario('gerente', permissoes=VER, gerente_de=(self.loja_b,)))
        self.assertEqual(ids(cliente.get(URL_USUARIOS)), {self.caio.pk})

    def test_administrador_global_ve_todos_menos_superusuario(self):
        cliente = cliente_logado(criar_usuario('adm', permissoes=VER + ('vendas.can_view_all_stores',)))
        visiveis = ids(cliente.get(URL_USUARIOS, {'ativo': 'todos'}, HTTP_X_LOJA='todas'))
        self.assertEqual(visiveis, {self.ana.pk, self.bia.pk, self.caio.pk, self.dani.pk, self.sem_loja.pk})

    def test_superusuario_ve_superusuarios(self):
        cliente = cliente_logado(criar_usuario('super2', superuser=True))
        self.assertIn(self.root.pk, ids(cliente.get(URL_USUARIOS)))

    def test_detalhe_respeita_escopo(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=VER, lojas=(self.loja_a,)))
        corpo = cliente.get(url_usuario(self.ana)).json()
        self.assertEqual(corpo['lojas'], [{'id': self.loja_a.pk, 'nome': 'Loja A'}])
        self.assertTrue(corpo['acesso_backoffice'])
        self.assertFalse(corpo['superusuario'])
        self.assertErro(cliente.get(url_usuario(self.caio)), 404, 'nao_encontrado')
        self.assertErro(cliente.get(url_usuario(self.root)), 404, 'nao_encontrado')

    def test_detalhe_informa_se_pode_editar(self):
        user = criar_usuario('gestor', permissoes=VER + ('accounts.change_user',), lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        self.assertFalse(cliente.get(url_usuario(self.ana)).json()['pode_editar'])
        livre = criar_usuario('livre', lojas=(self.loja_a,))
        self.assertTrue(cliente.get(url_usuario(livre)).json()['pode_editar'])
        proprio = cliente.get(url_usuario(user)).json()
        self.assertFalse(proprio['pode_editar'])
        self.assertIn('Meu perfil', proprio['motivo_bloqueio_edicao'])
