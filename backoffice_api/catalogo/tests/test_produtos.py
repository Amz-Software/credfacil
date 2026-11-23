"""Produtos: permissões, escopo de loja, validações, auditoria, simulação e PDF."""
import re

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from produtos.models import Produto

from .base import URL, CatalogoTestCase, criar_marca, criar_parcelamento, criar_produto, ids

URL_PRODUTOS = f'{URL}/produtos/'
CAMPOS_LISTA = {'id', 'codigo', 'nome', 'valor', 'entrada_cliente', 'marca', 'tipo', 'is_iphone', 'ativo'}
VER = ('produtos.view_produto',)
VER_TODOS = ('produtos.view_produto', 'produtos.view_all_produtos')


def url_produto(produto, acao: str = '') -> str:
    return f'{URL_PRODUTOS}{produto.pk}/' + (f'{acao}/' if acao else '')


class ProdutosBase(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.marca = criar_marca('Samsung')
        cls.marca_b = criar_marca('Exclusiva B', lojas=(cls.loja_b,))
        criar_parcelamento(cls.marca, 4, '20', '5')
        criar_parcelamento(cls.marca, 10, '50')
        cls.produto = criar_produto('Galaxy A15', cls.marca)
        cls.inativo = criar_produto('Galaxy Antigo', cls.marca, ativo=False)
        cls.da_loja_b = criar_produto('Produto B', cls.marca_b)
        cls.bloqueado = criar_produto('Bloqueado na A', cls.marca)
        cls.iphone = criar_produto('iPhone 15', cls.marca, is_iphone=True)
        cls.loja_a.produtos_bloqueados.add(cls.bloqueado)


class ListaDeProdutosTests(ProdutosBase):
    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('semperm', lojas=(self.loja_a,)))
        self.assertErro(cliente.get(URL_PRODUTOS), 403, 'proibido')

    def test_usuario_da_loja_ve_so_ativos_permitidos(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        resposta = cliente.get(URL_PRODUTOS)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(ids(resposta), {self.produto.pk})

    def test_lista_nao_expoe_campos_legados(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        item = cliente.get(URL_PRODUTOS).json()['results'][0]
        self.assertEqual(set(item), CAMPOS_LISTA)
        detalhe = cliente.get(url_produto(self.produto)).json()
        self.assertNotIn('valor_repasse_logista', detalhe)
        self.assertFalse([campo for campo in detalhe if re.match(r'valor_\d+_vezes', campo)])

    def test_ver_todos_inclui_inativos_e_filtra_situacao(self):
        cliente = cliente_logado(criar_usuario('admin', permissoes=VER_TODOS, lojas=(self.loja_a,)))
        todos = {self.produto.pk, self.inativo.pk, self.da_loja_b.pk, self.bloqueado.pk, self.iphone.pk}
        self.assertEqual(ids(cliente.get(URL_PRODUTOS)), todos)
        self.assertEqual(ids(cliente.get(URL_PRODUTOS, {'ativo': 'nao'})), {self.inativo.pk})
        self.assertErro(cliente.get(URL_PRODUTOS, {'ativo': 'talvez'}), 400, 'validacao', 'ativo')

    def test_sem_ver_todos_o_filtro_de_inativos_e_ignorado(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(ids(cliente.get(URL_PRODUTOS, {'ativo': 'nao'})), {self.produto.pk})

    def test_busca_por_nome_codigo_e_marca(self):
        cliente = cliente_logado(criar_usuario('admin', permissoes=VER_TODOS))
        self.assertEqual(ids(cliente.get(URL_PRODUTOS, {'busca': 'a15'})), {self.produto.pk})
        self.assertIn(self.produto.pk, ids(cliente.get(URL_PRODUTOS, {'busca': str(self.produto.codigo)})))
        self.assertEqual(ids(cliente.get(URL_PRODUTOS, {'marca': self.marca_b.pk})), {self.da_loja_b.pk})
        self.assertErro(cliente.get(URL_PRODUTOS, {'ordenar': 'senha'}), 400, 'validacao', 'ordenar')

    def test_ordenacao_por_valor(self):
        Produto.objects.filter(pk=self.produto.pk).update(valor='50.00')
        cliente = cliente_logado(criar_usuario('admin', permissoes=VER_TODOS))
        primeiro = cliente.get(URL_PRODUTOS, {'ordenar': 'valor', 'ativo': 'sim'}).json()['results'][0]
        self.assertEqual(primeiro['id'], self.produto.pk)

    def test_loja_fora_do_escopo_recebe_403(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.get(URL_PRODUTOS, HTTP_X_LOJA=str(self.loja_b.pk)), 403, 'proibido')

    def test_gerente_da_loja_b_ve_produto_exclusivo(self):
        cliente = cliente_logado(criar_usuario('gerente', permissoes=VER, gerente_de=(self.loja_b,)))
        self.assertIn(self.da_loja_b.pk, ids(cliente.get(URL_PRODUTOS)))

    def test_administrador_global_ve_permitidos_de_todas_as_lojas(self):
        user = criar_usuario('global', permissoes=VER + ('vendas.can_view_all_stores',))
        visiveis = ids(cliente_logado(user).get(URL_PRODUTOS, HTTP_X_LOJA='todas'))
        self.assertEqual(visiveis, {self.produto.pk, self.da_loja_b.pk, self.bloqueado.pk})


class DetalheESimulacaoTests(ProdutosBase):
    def setUp(self):
        self.cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))

    def test_detalhe_traz_simulacao_pela_tabela_da_marca(self):
        corpo = self.cliente.get(url_produto(self.produto)).json()
        self.assertEqual(corpo['nome'], 'Galaxy A15')
        simulacao = corpo['simulacao']
        self.assertEqual(simulacao['entrada'], '200.00')
        self.assertIsNone(simulacao['aviso'])
        self.assertEqual(simulacao['opcoes'], [
            {'qtd_vezes': 4, 'porcentagem_juros': '20.00', 'porcentagem_desconto': '5.00',
             'valor_financiado': '800.00', 'valor_total': '960.00', 'valor_parcela': '240.00'},
            {'qtd_vezes': 10, 'porcentagem_juros': '50.00', 'porcentagem_desconto': '0.00',
             'valor_financiado': '800.00', 'valor_total': '1200.00', 'valor_parcela': '120.00'},
        ])

    def test_marca_sem_parcelamento_vira_aviso(self):
        cliente = cliente_logado(criar_usuario('admin', permissoes=VER_TODOS))
        simulacao = cliente.get(url_produto(self.da_loja_b)).json()['simulacao']
        self.assertEqual(simulacao['opcoes'], [])
        self.assertIn('Nenhum parcelamento', simulacao['aviso'])

    def test_produto_de_outra_loja_responde_404(self):
        self.assertErro(self.cliente.get(url_produto(self.da_loja_b)), 404, 'nao_encontrado')
        self.assertErro(self.cliente.get(url_produto(self.bloqueado)), 404, 'nao_encontrado')

    def test_simulacao_com_entrada_informada(self):
        resposta = self.cliente.get(url_produto(self.produto, 'simulacao'), {'entrada': '400'})
        self.assertEqual(resposta.status_code, 200)
        opcao = resposta.json()['opcoes'][0]
        self.assertEqual((opcao['valor_financiado'], opcao['valor_total'], opcao['valor_parcela']),
                         ('600.00', '720.00', '180.00'))

    def test_simulacao_valida_a_entrada(self):
        abaixo = self.cliente.get(url_produto(self.produto, 'simulacao'), {'entrada': '100'})
        self.assertErro(abaixo, 422, 'regra_de_negocio')
        acima = self.cliente.get(url_produto(self.produto, 'simulacao'), {'entrada': '5000'})
        self.assertErro(acima, 400, 'validacao', 'entrada')
        self.assertErro(self.cliente.get(url_produto(self.produto, 'simulacao'), {'entrada': 'x'}), 400,
                        'validacao', 'entrada')


class EscritaDeProdutosTests(ProdutosBase):
    def test_criar_exige_permissao(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.post(URL_PRODUTOS, {'nome': 'Novo'}, format='json'), 403, 'proibido')

    def test_criar_produto(self):
        user = criar_usuario('cad', permissoes=VER + ('produtos.add_produto',), lojas=(self.loja_a,))
        corpo = {'nome': 'Moto G', 'valor': '1500.00', 'entrada_cliente': '300.00', 'marca': self.marca.pk}
        resposta = cliente_logado(user).post(URL_PRODUTOS, corpo, format='json', HTTP_X_LOJA=str(self.loja_a.pk))
        self.assertEqual(resposta.status_code, 201, resposta.content)
        produto = Produto.objects.get(pk=resposta.json()['id'])
        self.assertIsNotNone(produto.codigo)
        self.assertEqual((produto.criado_por, produto.loja), (user, self.loja_a))
        self.assertEqual(resposta.json()['simulacao']['opcoes'][0]['valor_financiado'], '1200.00')

    def test_criar_valida_campos(self):
        cliente = cliente_logado(criar_usuario('cad', permissoes=('produtos.add_produto',), lojas=(self.loja_a,)))
        self.assertErro(cliente.post(URL_PRODUTOS, {'valor': '10'}, format='json'), 400, 'validacao', 'nome')
        invalido = {'nome': 'X', 'valor': '100', 'entrada_cliente': '200'}
        self.assertErro(cliente.post(URL_PRODUTOS, invalido, format='json'), 400, 'validacao', 'entrada_cliente')
        negativo = {'nome': 'X', 'valor': '-1'}
        self.assertErro(cliente.post(URL_PRODUTOS, negativo, format='json'), 400, 'validacao', 'valor')

    def test_criar_com_marca_de_outra_loja_recebe_400(self):
        cliente = cliente_logado(criar_usuario('cad', permissoes=('produtos.add_produto',), lojas=(self.loja_a,)))
        corpo = {'nome': 'X', 'valor': '100', 'marca': self.marca_b.pk}
        self.assertErro(cliente.post(URL_PRODUTOS, corpo, format='json'), 400, 'validacao', 'marca')

    def test_editar_produto(self):
        user = criar_usuario('ed', permissoes=('produtos.change_produto',), lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        resposta = cliente.patch(url_produto(self.produto), {'valor': '1100.00'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.produto.refresh_from_db()
        self.assertEqual((str(self.produto.valor), self.produto.modificado_por), ('1100.00', user))
        self.assertErro(cliente.put(url_produto(self.produto), {'nome': 'X'}, format='json'), 405,
                        'metodo_nao_permitido')

    def test_editar_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.patch(url_produto(self.produto), {'nome': 'X'}, format='json'), 403, 'proibido')


class SituacaoDoProdutoTests(ProdutosBase):
    def test_desativar_e_ativar_sao_auditados(self):
        user = criar_usuario('gestor', permissoes=VER_TODOS + ('produtos.delete_produto',))
        cliente = cliente_logado(user)
        resposta = cliente.post(url_produto(self.produto, 'desativar'), {'motivo': 'Fora de linha'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertFalse(resposta.json()['ativo'])
        self.assertEqual(self.assertAuditado('produto_desativado', self.produto, usuario=user).motivo, 'Fora de linha')
        self.assertTrue(cliente.post(url_produto(self.produto, 'ativar')).json()['ativo'])
        self.assertAuditado('produto_ativado', self.produto)

    def test_desativar_exige_delete_produto(self):
        cliente = cliente_logado(criar_usuario('ed', permissoes=VER + ('produtos.change_produto',),
                                               lojas=(self.loja_a,)))
        self.assertErro(cliente.post(url_produto(self.produto, 'desativar')), 403, 'proibido')

    def test_get_em_acao_responde_405_sem_alterar(self):
        cliente = cliente_logado(criar_usuario('gestor', permissoes=VER_TODOS + ('produtos.delete_produto',)))
        self.assertErro(cliente.get(url_produto(self.produto, 'desativar')), 405, 'metodo_nao_permitido')
        self.produto.refresh_from_db()
        self.assertTrue(self.produto.ativo)


class RelatorioPDFTests(ProdutosBase):
    URL_PDF = f'{URL}/produtos/relatorio.pdf'

    def test_pdf_com_os_filtros_da_lista(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        resposta = cliente.get(self.URL_PDF, {'busca': 'galaxy', 'marca': self.marca.pk})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))

    def test_pdf_aceita_accept_pdf(self):
        cliente = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(self.URL_PDF, HTTP_ACCEPT='application/pdf').status_code, 200)

    def test_pdf_sem_permissao_e_por_post(self):
        sem_perm = cliente_logado(criar_usuario('semperm', lojas=(self.loja_a,)))
        self.assertErro(sem_perm.get(self.URL_PDF), 403, 'proibido')
        com_perm = cliente_logado(criar_usuario('vend', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(com_perm.post(self.URL_PDF), 405, 'metodo_nao_permitido')
