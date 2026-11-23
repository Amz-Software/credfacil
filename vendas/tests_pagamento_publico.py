"""Página pública de pagamento só pelo token aleatório (Pagamento.token_publico)."""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from vendas.models import Loja, Pagamento, Parcela, TipoPagamento, Venda
from vendas.tests_services import criar_cliente, criar_usuario


class PagamentoPublicoTests(TestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja', credfacil=True, chave_pix='chave@pix.com')
        cliente = criar_cliente(self.loja)
        venda = Venda.objects.create(cliente=cliente, vendedor=criar_usuario('v', self.loja), loja=self.loja,
                                     repasse_logista=Decimal('0'))
        tipo = TipoPagamento.objects.create(nome='IPX', parcelas=True)
        self.pagamento = Pagamento.objects.create(venda=venda, tipo_pagamento=tipo, valor=Decimal('300.00'),
                                                  parcelas=3, loja=self.loja, data_primeira_parcela=date.today())
        self.parcela = Parcela.objects.filter(pagamento=self.pagamento).order_by('numero_parcela').first()

    def test_pagina_publica_abre_pelo_token(self):
        resposta = self.client.get(f'/pagamento/{self.pagamento.token_publico}/')

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, f'/pagamento/{self.pagamento.token_publico}/informar-todos/')

    def test_url_antiga_por_id_nao_mostra_dados(self):
        resposta = self.client.get(f'/pagamento/{self.pagamento.pk}/')

        self.assertRedirects(resposta, reverse('vendas:consulta_pagamentos'), fetch_redirect_response=False)

    def test_token_inexistente_responde_404(self):
        self.assertEqual(self.client.get('/pagamento/00000000-0000-4000-8000-000000000000/').status_code, 404)

    def test_informar_parcela_exige_o_token_do_pagamento_dela(self):
        outro = Pagamento.objects.create(venda=self.pagamento.venda, tipo_pagamento=self.pagamento.tipo_pagamento,
                                         valor=Decimal('10'), parcelas=1, loja=self.loja,
                                         data_primeira_parcela=date.today())

        errado = self.client.post(f'/pagamento/{outro.token_publico}/parcela/{self.parcela.pk}/informar/')
        certo = self.client.post(f'/pagamento/{self.pagamento.token_publico}/parcela/{self.parcela.pk}/informar/')

        self.assertEqual(errado.status_code, 404)
        self.assertEqual(certo.status_code, 302)
        self.parcela.refresh_from_db()
        self.assertTrue(self.parcela.pagamento_efetuado)

    def test_consulta_por_cpf_lista_link_com_token(self):
        cliente = self.pagamento.venda.cliente
        resposta = self.client.post(reverse('vendas:consulta_pagamentos'),
                                    {'cpf': cliente.cpf, 'date_of_birth': cliente.nascimento.isoformat()})

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, f'/pagamento/{self.pagamento.token_publico}/')
        self.assertNotContains(resposta, f"/pagamento/{self.pagamento.pk}/'")

    def test_tokens_sao_distintos(self):
        self.assertNotEqual(Pagamento.objects.create(
            venda=self.pagamento.venda, tipo_pagamento=self.pagamento.tipo_pagamento, valor=Decimal('1'),
            parcelas=1, loja=self.loja, data_primeira_parcela=date.today(),
        ).token_publico, self.pagamento.token_publico)


class MigracaoTokenPublicoTests(TransactionTestCase):
    """A 0158 preenche os pagamentos existentes com tokens distintos antes da 0159 torná-los únicos."""

    ANTES = [('vendas', '0157_analisecreditocliente_segunda_compra_and_more')]
    DEPOIS = [('vendas', '0159_pagamento_token_publico_unico')]

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_preenche_tokens_distintos(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.ANTES)
        apps = executor.loader.project_state(self.ANTES).apps
        User = apps.get_model('accounts', 'User')
        Loja_ = apps.get_model('vendas', 'Loja')
        Cliente_ = apps.get_model('vendas', 'Cliente')
        Comprovantes_ = apps.get_model('vendas', 'ComprovantesCliente')
        Venda_ = apps.get_model('vendas', 'Venda')
        Tipo_ = apps.get_model('vendas', 'TipoPagamento')
        Pagamento_ = apps.get_model('vendas', 'Pagamento')
        loja = Loja_.objects.create(nome='L')
        cliente = Cliente_.objects.create(nome='C', telefone='1', cpf='1', nascimento=date(1990, 1, 1), rg='1',
                                          cep='1', endereco='R', bairro='B', cidade='X', loja=loja,
                                          comprovantes=Comprovantes_.objects.create())
        venda = Venda_.objects.create(cliente=cliente, vendedor=User.objects.create(username='u', email='u@t'),
                                      loja=loja, repasse_logista=Decimal('0'))
        tipo = Tipo_.objects.create(nome='IPX')
        for _ in range(3):
            Pagamento_.objects.create(venda=venda, tipo_pagamento=tipo, valor=Decimal('1'), parcelas=1, loja=loja,
                                      data_primeira_parcela=date.today())

        executor = MigrationExecutor(connection)
        executor.migrate(self.DEPOIS)
        tokens = list(executor.loader.project_state(self.DEPOIS).apps.get_model('vendas', 'Pagamento')
                      .objects.values_list('token_publico', flat=True))

        self.assertEqual(len(tokens), 3)
        self.assertEqual(len(set(tokens)), 3)
        self.assertNotIn(None, tokens)
