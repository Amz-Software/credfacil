"""Opções dos formulários de edição (tipos de pagamento, vendedores, produtos) e busca de clientes."""
from django.test import TestCase

from .fabricas import URL, CenarioVendas, cliente_logado, criar_cliente, criar_usuario, url_venda

URL_CLIENTES = f'{URL}clientes/'


class OpcoesEdicaoTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()

    def test_sem_permissao_403(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(url_venda(self.venda, 'opcoes-edicao/')).status_code, 403)

    def test_opcoes_da_loja_da_venda(self):
        user = criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        resposta = cliente_logado(user).get(url_venda(self.venda, 'opcoes-edicao/'))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual({t['nome'] for t in dados['tipos_pagamento']}, {'ENTRADA', 'IPX'})
        self.assertIn(self.vendedor.pk, [v['id'] for v in dados['vendedores']])
        self.assertEqual([p['nome'] for p in dados['produtos']], ['Galaxy A15', 'Galaxy A25'])
        self.assertEqual(dados['produtos'][0]['valor'], '1200.00')
        self.assertFalse(dados['produtos'][0]['serializado'])
        self.assertEqual(dados['parcelas_edicao_especial'], [4, 6, 8, 10, 12, 14])
        self.assertEqual(dados['limite_desconto_percentual'], 15)

    def test_produto_bloqueado_na_loja_fica_de_fora(self):
        self.loja_a.produtos_bloqueados.add(self.produto_novo)
        user = criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        dados = cliente_logado(user).get(url_venda(self.venda, 'opcoes-edicao/')).json()
        self.assertEqual([p['nome'] for p in dados['produtos']], ['Galaxy A15'])

    def test_venda_de_outra_loja_404(self):
        venda_b = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000002')
        user = criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        self.assertEqual(cliente_logado(user).get(url_venda(venda_b, 'opcoes-edicao/')).status_code, 404)


class ClientesDaVendaTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        criar_cliente(self.loja_a, 'Maria Souza', '12345678901')
        criar_cliente(self.loja_a, 'João Lima', '22233344455')
        criar_cliente(self.loja_b, 'Maria de Outra Loja', '99988877766')

    def test_sem_permissao_403(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL_CLIENTES).status_code, 403)

    def test_busca_no_escopo_com_cpf_mascarado(self):
        user = criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        resultados = cliente.get(URL_CLIENTES, {'busca': 'maria'}).json()['results']
        self.assertEqual(resultados, [
            {'id': resultados[0]['id'], 'nome': 'Maria Souza', 'cpf_mascarado': '***.456.789-**'},
        ])
        por_cpf = cliente.get(URL_CLIENTES, {'busca': '222.333'}).json()['results']
        self.assertEqual([c['nome'] for c in por_cpf], ['João Lima'])
        self.assertEqual(cliente.get(URL_CLIENTES).json()['count'], 2)
