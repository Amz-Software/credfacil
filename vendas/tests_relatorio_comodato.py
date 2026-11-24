"""Relatórios legados de vendas e solicitações: filtro, destaque e totais de comodato.

Venda de comodato tem `repasse_logista = 0`: o valor financiado (produto − entrada)
fica com a IPX. Os relatórios filtram por comodato e separam os totais.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, SimpleTestCase, TestCase

from accounts.models import User
from produtos.models import Marca, Produto
from vendas.forms import RelatorioSolicitacoesForm, RelatorioVendasForm
from vendas.models import (
    AnaliseCreditoCliente, Cliente, ComprovantesCliente, Loja, Pagamento,
    ProdutoVenda, TipoPagamento, Venda,
)
from vendas.views import FolhaRelatorioSolicitacoesView, FolhaRelatorioVendasView
from vendas.views.relatorios import parse_filtro_sim_nao


def _cliente(nome, loja):
    return Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf='12345678900',
        nascimento=date(1990, 1, 1), rg='123', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(),
    )


class ParseFiltroSimNaoTests(SimpleTestCase):
    def test_converte_valores_da_querystring(self):
        self.assertIs(parse_filtro_sim_nao('True'), True)
        self.assertIs(parse_filtro_sim_nao('1'), True)
        self.assertIs(parse_filtro_sim_nao('false'), False)
        self.assertIs(parse_filtro_sim_nao('0'), False)

    def test_vazio_ou_invalido_significa_todos(self):
        self.assertIsNone(parse_filtro_sim_nao(''))
        self.assertIsNone(parse_filtro_sim_nao(None))
        self.assertIsNone(parse_filtro_sim_nao('talvez'))


class RelatorioComodatoCenario(TestCase):
    """Uma venda comum e uma de comodato do mesmo produto (R$ 1.200, entrada R$ 200)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.user = User.objects.create_user(
            username='gestor', email='gestor@teste.com', password='x', loja=self.loja,
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_generate_report_sale'),
        )
        self.produto = Produto.objects.create(
            nome='Galaxy', valor=Decimal('1200.00'), entrada_cliente=Decimal('200.00'),
            marca=Marca.objects.create(nome='Samsung'),
        )
        self.tipo_entrada = TipoPagamento.objects.create(nome='ENTRADA', caixa=True)
        self.tipo_ipx = TipoPagamento.objects.create(nome='IPX', parcelas=True)

        self.venda_comum = self._venda('Cliente Comum', comodato=False, repasse=Decimal('1000.00'))
        self.venda_comodato = self._venda('Cliente Comodato', comodato=True, repasse=Decimal('0'))

    def _venda(self, nome, *, comodato, repasse):
        cliente = _cliente(nome, self.loja)
        venda = Venda.objects.create(
            cliente=cliente, vendedor=self.user, loja=self.loja,
            repasse_logista=repasse, comodato=comodato,
        )
        ProdutoVenda.objects.create(
            venda=venda, produto=self.produto, valor_unitario=Decimal('1200.00'),
            quantidade=1, loja=self.loja,
        )
        for tipo, valor, parcelas in (
            (self.tipo_entrada, Decimal('200.00'), 1),
            (self.tipo_ipx, Decimal('1200.00'), 10),
        ):
            Pagamento.objects.create(
                venda=venda, tipo_pagamento=tipo, valor=valor, parcelas=parcelas,
                loja=self.loja, data_primeira_parcela=date.today(),
            )
        AnaliseCreditoCliente.objects.create(
            cliente=cliente, produto=self.produto, loja=self.loja, status='A',
            numero_parcelas='10', data_pagamento='10', comodato=comodato, venda=venda,
        )
        return venda

    def _get(self, view, params=None):
        request = self.factory.get('/relatorio/', params or {})
        request.user = self.user
        request.session = SessionStore()
        request.session['loja_id'] = self.loja.id
        request._messages = FallbackStorage(request)
        return view.as_view()(request)


class RelatorioVendasComodatoTests(RelatorioComodatoCenario):
    def test_form_tem_filtro_comodato_todos_sim_nao(self):
        # Arrange / Act
        form = RelatorioVendasForm(data={'comodato': 'True'}, loja=self.loja.id, user=self.user)

        # Assert
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['comodato'], True)
        self.assertEqual(
            [valor for valor, _ in form.fields['comodato'].choices], ['', 'True', 'False'],
        )

    def test_filtro_sim_lista_somente_vendas_de_comodato(self):
        response = self._get(FolhaRelatorioVendasView, {'comodato': 'True'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [v.pk for v in response.context_data['vendas']], [self.venda_comodato.pk],
        )

    def test_filtro_nao_lista_somente_vendas_comuns(self):
        response = self._get(FolhaRelatorioVendasView, {'comodato': 'False'})

        self.assertEqual(
            [v.pk for v in response.context_data['vendas']], [self.venda_comum.pk],
        )

    def test_sem_filtro_lista_todas(self):
        response = self._get(FolhaRelatorioVendasView, {'comodato': ''})

        self.assertEqual(response.context_data['total_vendas'], 2)

    def test_totais_separam_comodato_e_vendas_comuns(self):
        # Act
        response = self._get(FolhaRelatorioVendasView)
        resumo = response.context_data['resumo_comodato']

        # Assert: totais existentes mantidos
        self.assertEqual(response.context_data['total_repasse'], Decimal('1000.00'))
        self.assertEqual(response.context_data['total_valor'], Decimal('2800.00'))
        # comuns: repasse ao lojista
        self.assertEqual(resumo['comum']['quantidade'], 1)
        self.assertEqual(resumo['comum']['repasse'], Decimal('1000.00'))
        self.assertEqual(resumo['comum']['valor'], Decimal('1400.00'))
        # comodato: repasse zero, valor financiado fica com a IPX
        self.assertEqual(resumo['comodato']['quantidade'], 1)
        self.assertEqual(resumo['comodato']['repasse'], Decimal('0'))
        self.assertEqual(resumo['comodato']['financiado'], Decimal('1000.00'))
        self.assertEqual(resumo['comodato']['valor'], Decimal('1400.00'))

    def test_folha_destaca_linha_e_mostra_resumo(self):
        response = self._get(FolhaRelatorioVendasView)
        html = response.render().content.decode()

        self.assertIn('class="selo-comodato">Comodato</span>', html)
        self.assertEqual(html.count('class="linha-comodato"'), 2)  # linha da venda + linha do resumo
        self.assertIn('Repasse ao lojista (vendas comuns)', html)
        self.assertIn('Fica com a IPX (comodato)', html)


class RelatorioSolicitacoesComodatoTests(RelatorioComodatoCenario):
    def test_form_tem_filtro_comodato(self):
        form = RelatorioSolicitacoesForm(data={'comodato': 'False'}, loja=self.loja.id, user=self.user)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['comodato'], False)

    def test_filtro_sim_usa_comodato_da_analise(self):
        response = self._get(FolhaRelatorioSolicitacoesView, {'comodato': 'True'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [c.pk for c in response.context_data['solicitacoes']],
            [self.venda_comodato.cliente_id],
        )

    def test_filtro_nao_exclui_comodato(self):
        response = self._get(FolhaRelatorioSolicitacoesView, {'comodato': 'False'})

        self.assertEqual(
            [c.pk for c in response.context_data['solicitacoes']],
            [self.venda_comum.cliente_id],
        )

    def test_totais_separam_solicitacoes_de_comodato(self):
        response = self._get(FolhaRelatorioSolicitacoesView)
        ctx = response.context_data

        self.assertEqual(ctx['total_vendas'], 2)
        self.assertEqual(ctx['solicitacoes_comodato'], 1)
        self.assertEqual(ctx['solicitacoes_comuns'], 1)
        self.assertEqual(ctx['total_repasse'], Decimal('1000.00'))
        self.assertEqual(ctx['resumo_comodato']['comum']['repasse'], Decimal('1000.00'))
        self.assertEqual(ctx['resumo_comodato']['comodato']['financiado'], Decimal('1000.00'))

    def test_folha_destaca_solicitacao_de_comodato(self):
        html = self._get(FolhaRelatorioSolicitacoesView).render().content.decode()

        self.assertIn('class="selo-comodato">Comodato</span>', html)
        self.assertIn('Fica com a IPX (comodato)', html)
