"""Relatórios legados de vendas e solicitações: filtro por marca e por iPhone."""

from decimal import Decimal

from produtos.models import Marca, Produto
from vendas.forms import RelatorioSolicitacoesForm, RelatorioVendasForm
from vendas.views import FolhaRelatorioSolicitacoesView, FolhaRelatorioVendasView

from .tests_relatorio_comodato import RelatorioComodatoCenario


class RelatorioMarcaCenario(RelatorioComodatoCenario):
    """Duas vendas de Galaxy (Samsung) e uma de iPhone (Apple)."""

    def setUp(self):
        super().setUp()
        self.apple = Marca.objects.create(nome='Apple')
        self.produto = Produto.objects.create(
            nome='iPhone 13', valor=Decimal('3000.00'), entrada_cliente=Decimal('500.00'),
            marca=self.apple, is_iphone=True,
        )
        self.venda_iphone = self._venda('Cliente iPhone', comodato=False, repasse=Decimal('2500.00'))


class RelatorioVendasMarcaTests(RelatorioMarcaCenario):
    def _ids(self, params):
        response = self._get(FolhaRelatorioVendasView, params)
        return sorted(v.pk for v in response.context_data['vendas'])

    def test_form_tem_filtros_de_marca_e_iphone(self):
        form = RelatorioVendasForm(
            data={'marcas': [self.apple.pk], 'iphone': 'True'}, loja=self.loja.id, user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.cleaned_data['marcas']), [self.apple])
        self.assertIs(form.cleaned_data['iphone'], True)

    def test_filtra_por_marca(self):
        self.assertEqual(self._ids({'marcas': [self.apple.pk]}), [self.venda_iphone.pk])

    def test_somente_iphone_e_sem_iphone(self):
        self.assertEqual(self._ids({'iphone': 'True'}), [self.venda_iphone.pk])
        self.assertEqual(
            self._ids({'iphone': 'False'}), sorted([self.venda_comum.pk, self.venda_comodato.pk]),
        )


class RelatorioSolicitacoesMarcaTests(RelatorioMarcaCenario):
    def _ids(self, params):
        response = self._get(FolhaRelatorioSolicitacoesView, params)
        return sorted(c.pk for c in response.context_data['solicitacoes'])

    def test_form_tem_filtros_de_marca_e_iphone(self):
        form = RelatorioSolicitacoesForm(data={'iphone': 'False'}, loja=self.loja.id, user=self.user)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['iphone'], False)

    def test_filtra_por_marca_e_iphone(self):
        self.assertEqual(self._ids({'marcas': [self.apple.pk]}), [self.venda_iphone.cliente_id])
        self.assertEqual(self._ids({'iphone': 'True'}), [self.venda_iphone.cliente_id])
        self.assertEqual(
            self._ids({'iphone': 'False'}),
            sorted([self.venda_comum.cliente_id, self.venda_comodato.cliente_id]),
        )
