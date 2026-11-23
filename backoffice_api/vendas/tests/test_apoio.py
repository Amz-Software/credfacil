"""Produtos vendidos, autorização de gerente e busca global."""
from django.test import TestCase

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import SENHA_FORTE

from .fabricas import URL, CenarioVendas, cliente_logado, criar_usuario

URL_PRODUTOS = f'{URL}produtos-vendidos/'
URL_AUTORIZACAO = f'{URL}autorizacao-gerente/'
URL_BUSCA = f'{URL}busca/'


class ProdutosVendidosTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda_a = self.criar_venda_manual()
        self.venda_b = self.criar_venda_manual(self.loja_b, cpf='11122233344', nome='Pedro', imei='350000000000002')

    def ids(self, resposta):
        return [i['venda']['id'] for i in resposta.json()['results']]

    def test_sem_permissao_403(self):
        cliente = cliente_logado(criar_usuario('sem', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL_PRODUTOS).status_code, 403)

    def test_escopo_filtros_e_cpf_mascarado(self):
        user = criar_usuario('pv', permissoes=('vendas.view_produtovenda',), lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        resposta = cliente.get(URL_PRODUTOS)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.ids(resposta), [self.venda_a.pk])
        self.assertEqual(resposta.json()['results'][0]['cpf_mascarado'], '***.456.789-**')
        self.assertEqual(self.ids(cliente.get(URL_PRODUTOS, {'loja': self.loja_b.pk})), [self.venda_a.pk])
        self.assertEqual(self.ids(cliente.get(URL_PRODUTOS, {'imei': '0001'})), [self.venda_a.pk])
        self.assertEqual(self.ids(cliente.get(URL_PRODUTOS, {'cpf': '999'})), [])
        self.assertEqual(self.ids(cliente.get(URL_PRODUTOS, {'nome': 'galaxy'})), [self.venda_a.pk])
        self.assertEqual(cliente.get(URL_PRODUTOS, {'ordenar': 'x'}).status_code, 400)

    def test_permissao_global_de_produtos_vendidos(self):
        user = criar_usuario('pvg', permissoes=('vendas.view_produtovenda', 'vendas.can_view_all_products_sold'))
        cliente = cliente_logado(user)
        self.assertEqual(sorted(self.ids(cliente.get(URL_PRODUTOS))), sorted([self.venda_a.pk, self.venda_b.pk]))
        self.assertEqual(self.ids(cliente.get(URL_PRODUTOS, {'cpf': '111.222'})), [self.venda_b.pk])

    def test_post_405(self):
        user = criar_usuario('pv', permissoes=('vendas.view_produtovenda',), lojas=(self.loja_a,))
        self.assertEqual(cliente_logado(user).post(URL_PRODUTOS, {}).status_code, 405)


class AutorizacaoGerenteTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        self.gerente = criar_usuario('gerente_a', gerente_de=(self.loja_a,), acesso_backoffice=False)
        self.cliente = cliente_logado(criar_usuario('caixa', permissoes=('vendas.change_venda',), lojas=(self.loja_a,)))

    def autorizar(self, **dados):
        corpo = {'usuario': 'gerente_a', 'senha': SENHA_FORTE, 'venda': self.venda.pk, **dados}
        return self.cliente.post(URL_AUTORIZACAO, {k: v for k, v in corpo.items() if v is not None}, format='json')

    def test_gerente_da_loja_autoriza_sem_criar_sessao(self):
        resposta = self.autorizar()
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.json()['gerente']['id'], self.gerente.pk)
        self.assertEqual(resposta.json()['loja']['id'], self.loja_a.pk)
        registro = RegistroAuditoria.objects.get(acao='autorizacao_gerente_concedida')
        self.assertEqual(registro.usuario_nome, 'caixa')
        self.assertEqual(self.cliente.get('/api/bo/v1/me/').json()['usuario'], 'caixa')

    def test_senha_errada_e_nao_gerente_sao_negadas_e_auditadas(self):
        self.assertEqual(self.autorizar(senha='errada').status_code, 403)
        criar_usuario('outro', lojas=(self.loja_a,), acesso_backoffice=False)
        resposta = self.autorizar(usuario='outro')
        self.assertEqual(resposta.status_code, 403)
        self.assertIn('não é gerente', resposta.json()['erro']['mensagem'])
        motivos = sorted(RegistroAuditoria.objects.filter(acao='autorizacao_gerente_negada')
                         .values_list('dados__motivo', flat=True))
        self.assertEqual(motivos, ['credenciais', 'nao_gerente'])

    def test_loja_pela_requisicao_e_validacoes(self):
        self.assertEqual(self.autorizar(venda=None).status_code, 200)  # única loja do escopo
        self.assertEqual(self.autorizar(venda=None, loja=self.loja_b.pk).status_code, 403)
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000015')
        self.assertEqual(self.autorizar(venda=outra.pk).status_code, 400)
        self.assertIn('senha', self.autorizar(senha='').json()['erro']['campos'])

    def test_sem_permissao_403(self):
        cliente = cliente_logado(criar_usuario('leitor', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        resposta = cliente.post(URL_AUTORIZACAO, {'usuario': 'gerente_a', 'senha': SENHA_FORTE}, format='json')
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.cliente.get(URL_AUTORIZACAO).status_code, 405)


class BuscaGlobalTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        self.outra = self.criar_venda_manual(self.loja_b, cpf='12345600000', nome='Maria B', imei='350000000000016')
        self.cliente = cliente_logado(criar_usuario('busca', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))

    def test_busca_por_numero_nome_cpf_e_imei_no_escopo(self):
        for termo in (str(self.venda.pk), 'maria', '123456', '350000000000001'):
            resposta = self.cliente.get(URL_BUSCA, {'termo': termo})
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual([r['id'] for r in resposta.json()], [self.venda.pk], termo)
        resultado = self.cliente.get(URL_BUSCA, {'termo': 'maria'}).json()[0]
        self.assertEqual(resultado['tipo'], 'venda')
        self.assertIn('***.456.789-**', resultado['descricao'])

    def test_limite_de_oito_e_termo_curto(self):
        for indice in range(10):
            self.criar_venda_manual(cpf=f'5556667770{indice}', nome=f'Cliente Teste {indice}', imei=f'36{indice:013d}')
        self.assertEqual(len(self.cliente.get(URL_BUSCA, {'termo': 'teste'}).json()), 8)
        self.assertEqual(self.cliente.get(URL_BUSCA, {'termo': 'a'}).status_code, 400)

    def test_sem_permissao_403(self):
        cliente = cliente_logado(criar_usuario('sem', lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL_BUSCA, {'termo': 'maria'}).status_code, 403)
