"""Relatórios legados de contas a receber e parcelas: filtro, destaque e totais de comodato."""

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from accounts.models import User
from financeiro.forms import (
    RelatorioContasAReceberAvancadoForm, RelatorioContasAReceberForm, RelatorioParcelasForm,
)
from financeiro.views import (
    FolhaRelatorioContasAReceberAvancadoView, FolhaRelatorioContasAReceberView,
    RelatorioParcelasExcelView,
)
from vendas.models import (
    Cliente, ComprovantesCliente, Loja, Pagamento, Parcela, TipoPagamento, Venda,
)

PERMISSOES = ('can_genarate_report_payments', 'can_view_all_payments')


class RelatoriosFinanceirosComodatoTests(TestCase):
    """Pagamento IPX comum (2 x R$ 100) e de comodato (2 x R$ 150): 1 parcela paga hoje e 1 a vencer."""

    def setUp(self):
        self.factory = RequestFactory()
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.user = User.objects.create_user(
            username='financeiro', email='fin@teste.com', password='x', loja=self.loja,
        )
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=PERMISSOES))
        self.tipo = TipoPagamento.objects.create(nome='IPX', parcelas=True, caixa=False)
        self.hoje = date.today()

        self.pag_comum = self._pagamento('Cliente Comum', comodato=False, valor_parcela=Decimal('100.00'))
        self.pag_comodato = self._pagamento('Cliente Comodato', comodato=True, valor_parcela=Decimal('150.00'))

    def _pagamento(self, nome, *, comodato, valor_parcela):
        cliente = Cliente.objects.create(
            nome=nome, telefone='91999999999', cpf='12345678900',
            nascimento=date(1990, 1, 1), rg='123', cep='66000000',
            endereco='Rua A', bairro='Centro', cidade='Belém', loja=self.loja,
            comprovantes=ComprovantesCliente.objects.create(),
        )
        venda = Venda.objects.create(
            cliente=cliente, vendedor=self.user, loja=self.loja,
            repasse_logista=Decimal('0') if comodato else Decimal('200.00'), comodato=comodato,
        )
        pagamento = Pagamento.objects.create(
            venda=venda, tipo_pagamento=self.tipo, valor=valor_parcela * 2,
            parcelas=2, loja=self.loja, data_primeira_parcela=self.hoje,
        )
        # O signal gera parcelas automáticas; troca por parcelas com situação controlada
        pagamento.parcelas_pagamento.all().delete()
        Parcela.objects.create(
            pagamento=pagamento, numero_parcela=1, valor=valor_parcela, valor_pago=valor_parcela,
            data_vencimento=self.hoje, data_pagamento=self.hoje, pago=True, loja=self.loja,
        )
        Parcela.objects.create(
            pagamento=pagamento, numero_parcela=2, valor=valor_parcela,
            data_vencimento=self.hoje + timedelta(days=10), pago=False, loja=self.loja,
        )
        return pagamento

    def _get(self, view, params):
        request = self.factory.get('/relatorio/', params)
        request.user = self.user
        request.session = SessionStore()
        request.session['loja_id'] = self.loja.id
        request._messages = FallbackStorage(request)
        return view.as_view()(request)

    def _periodo(self, **extra):
        return {
            'data_inicial': (self.hoje - timedelta(days=1)).isoformat(),
            'data_final': (self.hoje + timedelta(days=30)).isoformat(),
            **extra,
        }

    # --- formulários ---

    def test_forms_financeiros_tem_filtro_comodato(self):
        for form_class in (
            RelatorioContasAReceberForm, RelatorioContasAReceberAvancadoForm, RelatorioParcelasForm,
        ):
            with self.subTest(form=form_class.__name__):
                campo = form_class.base_fields['comodato']
                self.assertEqual(campo.label, 'Aparelho de comodato')
                self.assertEqual([v for v, _ in campo.choices], ['', 'True', 'False'])
                self.assertIs(campo.clean('True'), True)
                self.assertIs(campo.clean('False'), False)
                self.assertFalse(campo.clean(''))  # Todos: vazio, sem filtro

    # --- contas a receber (simples) ---

    def test_contas_a_receber_filtra_comodato(self):
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='todos', comodato='True'))

        contas = response.context_data['contas_a_receber']
        self.assertEqual([c.pk for c in contas], [self.pag_comodato.pk])

    def test_contas_a_receber_filtro_nao_exclui_comodato(self):
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='todos', comodato='False'))

        contas = response.context_data['contas_a_receber']
        self.assertEqual([c.pk for c in contas], [self.pag_comum.pk])

    def test_contas_a_receber_separa_totais(self):
        # Act
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='todos'))
        ctx = response.context_data
        comodato, comum = ctx['totais_comodato']['comodato'], ctx['totais_comodato']['comum']

        # Assert: total geral mantido e igual à soma dos grupos
        self.assertEqual(ctx['total'], Decimal('500.00'))
        self.assertEqual(comum['quantidade'], 1)
        self.assertEqual(comum['total'], Decimal('200.00'))
        self.assertEqual(comodato['quantidade'], 1)
        self.assertEqual(comodato['total'], Decimal('300.00'))
        self.assertEqual(comodato['total_a_vencer'] + comum['total_a_vencer'], ctx['total_a_vencer'])

    def test_contas_a_receber_destaca_comodato_na_folha(self):
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='todos'))
        html = response.render().content.decode()

        self.assertIn('<span class="selo-comodato">COMODATO</span>', html)
        self.assertIn('Comodato (sem repasse ao lojista) (1):', html)
        self.assertIn('Vendas comuns (1):', html)

    def test_contas_a_receber_sem_comodato_nao_mostra_linhas_de_comodato(self):
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='todos', comodato='False'))
        html = response.render().content.decode()

        self.assertNotIn('Comodato (sem repasse ao lojista)', html)
        self.assertNotIn('Vendas comuns (', html)

    def test_contas_a_receber_visao_por_parcelas_pagas_separa_totais(self):
        response = self._get(FolhaRelatorioContasAReceberView, self._periodo(status='pago'))
        ctx = response.context_data

        self.assertTrue(ctx['list_by_parcelas'])
        self.assertEqual(ctx['total_pago'], Decimal('250.00'))
        self.assertEqual(ctx['totais_comodato']['comodato']['total_pago'], Decimal('150.00'))
        self.assertEqual(ctx['totais_comodato']['comum']['total_pago'], Decimal('100.00'))

    def test_contas_a_receber_visao_por_parcelas_filtra_comodato(self):
        response = self._get(
            FolhaRelatorioContasAReceberView, self._periodo(status='pago', comodato='True'),
        )

        parcelas = response.context_data['parcelas']
        self.assertEqual({p.pagamento_id for p in parcelas}, {self.pag_comodato.pk})

    # --- contas a receber (avançado) ---

    def test_avancado_filtra_e_conta_comodato(self):
        todos = self._get(FolhaRelatorioContasAReceberAvancadoView, {}).context_data
        so_comodato = self._get(FolhaRelatorioContasAReceberAvancadoView, {'comodato': 'True'}).context_data

        self.assertEqual(todos['qtd_comodato'], 1)
        self.assertEqual(todos['qtd_comum'], 1)
        self.assertEqual([p.pk for p in so_comodato['contas']], [self.pag_comodato.pk])

    def test_avancado_destaca_comodato(self):
        html = self._get(FolhaRelatorioContasAReceberAvancadoView, {}).render().content.decode()

        self.assertIn('<span class="selo-comodato">Comodato</span>', html)

    def test_avancado_sem_comodato_nao_mostra_contagem_de_comodato(self):
        html = self._get(FolhaRelatorioContasAReceberAvancadoView, {'comodato': 'False'}).render().content.decode()

        self.assertNotIn('(sem repasse ao lojista)', html)
        self.assertNotIn('Vendas comuns:', html)

    # --- parcelas (Excel) ---

    def _planilha(self, params):
        response = self._get(RelatorioParcelasExcelView, params)
        self.assertEqual(response.status_code, 200)
        return openpyxl.load_workbook(BytesIO(response.content)).active

    @staticmethod
    def _linhas(ws):
        return [[c.value for c in row] for row in ws.iter_rows()]

    def test_excel_parcelas_tem_coluna_comodato(self):
        ws = self._planilha({})
        linhas = self._linhas(ws)
        cabecalho = linhas[4]
        dados = {linha[1]: linha for linha in linhas[5:7]}

        self.assertEqual(cabecalho[:4], ['Loja', 'Cliente', 'Aparelho', 'Comodato'])
        self.assertEqual(dados['Cliente Comodato'][3], 'Sim')
        self.assertEqual(dados['Cliente Comum'][3], 'Não')

    def test_excel_parcelas_filtra_comodato(self):
        linhas = self._linhas(self._planilha({'comodato': 'True'}))

        clientes = [linha[1] for linha in linhas[5:] if linha[1] and linha[1].startswith('Cliente')]
        self.assertEqual(clientes, ['Cliente Comodato'])

    def test_excel_parcelas_separa_totais(self):
        linhas = self._linhas(self._planilha({}))
        rodape = {linha[0]: linha for linha in linhas if linha[0] in (
            'Total geral', 'Vendas comuns', 'Comodato (sem repasse ao lojista)',
        )}
        col_total = linhas[4].index('Total')

        self.assertEqual(rodape['Total geral'][1], '2 cliente(s)')
        self.assertEqual(rodape['Total geral'][col_total], 'R$ 500,00')
        self.assertEqual(rodape['Vendas comuns'][col_total], 'R$ 200,00')
        self.assertEqual(rodape['Comodato (sem repasse ao lojista)'][col_total], 'R$ 300,00')
