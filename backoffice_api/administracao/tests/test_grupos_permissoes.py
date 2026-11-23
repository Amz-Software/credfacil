"""Grupos (com a regra de só conceder o que possui), lista de permissões e matriz."""
from django.contrib.auth.models import Group

from backoffice_api.tests.fabricas import cliente_logado, criar_usuario

from .base import URL, AdministracaoTestCase, criar_grupo, ids, permissao

URL_GRUPOS = f'{URL}/grupos/'
URL_PERMISSOES = f'{URL}/permissoes/'
URL_MATRIZ = f'{URL}/permissoes/matriz/'
GESTAO = ('auth.view_group', 'auth.add_group', 'auth.change_group', 'vendas.view_cliente')


class GruposTests(AdministracaoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vendedor = criar_grupo('VENDEDOR', 'vendas.view_cliente')
        cls.admin = criar_grupo('ADMINISTRADOR', 'vendas.view_cliente', 'vendas.delete_venda')

    def setUp(self):
        self.gestor = criar_usuario('gestor', permissoes=GESTAO, grupos=('VENDEDOR',))
        self.cliente = cliente_logado(self.gestor)

    def test_sem_permissao_recebe_403(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_GRUPOS), 403, 'proibido')

    def test_lista_com_contagens_e_pode_editar(self):
        resposta = self.cliente.get(URL_GRUPOS)
        por_nome = {g['nome']: g for g in resposta.json()['results']}
        self.assertEqual((por_nome['VENDEDOR']['total_permissoes'], por_nome['VENDEDOR']['total_usuarios']), (1, 1))
        self.assertTrue(por_nome['VENDEDOR']['pode_editar'])
        self.assertFalse(por_nome['ADMINISTRADOR']['pode_editar'])
        self.assertEqual(ids(self.cliente.get(URL_GRUPOS, {'busca': 'admin'})), {self.admin.pk})

    def test_detalhe_traz_permissoes_com_rotulo(self):
        corpo = self.cliente.get(f'{URL_GRUPOS}{self.vendedor.pk}/').json()
        self.assertEqual(corpo['permissoes'][0]['codigo'], 'vendas.view_cliente')
        self.assertTrue(corpo['permissoes'][0]['nome'].startswith('Ver '))

    def test_criar_com_o_que_possui_e_auditar(self):
        corpo = {'nome': 'Atendimento', 'permissoes': [permissao('vendas.view_cliente').pk]}
        resposta = self.cliente.post(URL_GRUPOS, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        grupo = Group.objects.get(name='Atendimento')
        self.assertEqual(self.assertAuditado('grupo_criado', grupo).dados['permissoes'], ['vendas.view_cliente'])

    def test_criar_com_permissao_que_nao_possui_recebe_403(self):
        corpo = {'nome': 'Poderoso', 'permissoes': [permissao('vendas.delete_venda').pk]}
        self.assertErro(self.cliente.post(URL_GRUPOS, corpo, format='json'), 403, 'proibido', 'permissoes')
        self.assertFalse(Group.objects.filter(name='Poderoso').exists())

    def test_nome_duplicado_recebe_400(self):
        self.assertErro(self.cliente.post(URL_GRUPOS, {'nome': 'vendedor'}, format='json'), 400, 'validacao', 'nome')

    def test_nao_edita_grupo_com_mais_acesso(self):
        resposta = self.cliente.patch(f'{URL_GRUPOS}{self.admin.pk}/', {'nome': 'X'}, format='json')
        self.assertErro(resposta, 403, 'proibido')
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.name, 'ADMINISTRADOR')

    def test_editar_audita_permissoes_adicionadas_e_removidas(self):
        grupo = criar_grupo('Suporte', 'vendas.view_cliente')
        corpo = {'nome': 'Suporte N1', 'permissoes': [permissao('auth.view_group').pk]}
        resposta = self.cliente.patch(f'{URL_GRUPOS}{grupo.pk}/', corpo, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        dados = self.assertAuditado('grupo_alterado', grupo).dados
        self.assertEqual(dados['permissoes_adicionadas'], ['auth.view_group'])
        self.assertEqual(dados['permissoes_removidas'], ['vendas.view_cliente'])
        self.assertEqual(dados['nome'], {'antes': 'Suporte', 'depois': 'Suporte N1'})

    def test_superusuario_edita_qualquer_grupo_e_nao_ha_exclusao(self):
        cliente = cliente_logado(criar_usuario('root', superuser=True))
        self.assertEqual(cliente.patch(f'{URL_GRUPOS}{self.admin.pk}/', {'nome': 'ADM'}, format='json').status_code,
                         200)
        self.assertErro(cliente.delete(f'{URL_GRUPOS}{self.admin.pk}/'), 405, 'metodo_nao_permitido')


class PermissoesTests(AdministracaoTestCase):
    def test_lista_exige_view_permission(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_PERMISSOES), 403, 'proibido')

    def test_lista_com_busca_e_rotulo_traduzido(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=('auth.view_permission',)))
        resposta = cliente.get(URL_PERMISSOES, {'busca': 'add_marca'})
        item = resposta.json()['results'][0]
        self.assertEqual(item['codigo'], 'produtos.add_marca')
        self.assertEqual(item['nome'], 'Adicionar Marca')
        self.assertEqual(item['acao'], 'add')
        customizada = cliente.get(URL_PERMISSOES, {'busca': 'view_all_produtos'}).json()['results'][0]
        self.assertEqual(customizada['nome'], 'Ver todos: produtos')

    def test_matriz_agrupada_com_pode_conceder(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=GESTAO))
        apps = {a['app_label']: a for a in cliente.get(URL_MATRIZ).json()['apps']}
        marca = next(m for m in apps['produtos']['modelos'] if m['modelo'] == 'marca')
        self.assertEqual([p['acao'] for p in marca['permissoes']], ['view', 'add', 'change', 'delete'])
        cliente_modelo = next(m for m in apps['vendas']['modelos'] if m['modelo'] == 'cliente')
        conceder = {p['codename']: p['pode_conceder'] for p in cliente_modelo['permissoes']}
        self.assertTrue(conceder['view_cliente'])
        self.assertFalse(conceder['delete_cliente'])

    def test_matriz_exige_alguma_permissao_de_gestao(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_MATRIZ), 403, 'proibido')
        cliente = cliente_logado(criar_usuario('cad', permissoes=('accounts.add_user',)))
        self.assertEqual(cliente.get(URL_MATRIZ).status_code, 200)
