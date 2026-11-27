"""Relatórios de vendas e solicitações (API do backoffice): filtro por marca e por iPhone."""
from decimal import Decimal

from django.test import TestCase

from backoffice_api.painel.tests import cenario
from backoffice_api.tests.fabricas import criar_loja
from produtos.models import Marca, Produto
from vendas.models import AnaliseCreditoCliente, ProdutoVenda

from ..filtros import FiltrosSolicitacoesSerializer, FiltrosVendasSerializer, descrever_filtros
from ..servicos import solicitacoes, vendas
from ..servicos.comum import EscopoRelatorio
from vendas.models import Loja


def escopo_total() -> EscopoRelatorio:
    return EscopoRelatorio(lojas_escolhidas=(), aplicar_escopo=lambda qs, campo: qs)


class CenarioMarcas(TestCase):
    """Ana comprou Galaxy (Samsung); Bia comprou iPhone (Apple); Caio levou Galaxy + iPhone."""

    def setUp(self):
        self.loja = criar_loja('Loja Alfa')
        self.apple = Marca.objects.create(nome='Apple')
        self.iphone = Produto.objects.create(
            nome='iPhone 13', valor=Decimal('3000.00'), entrada_cliente=Decimal('500.00'),
            marca=self.apple, is_iphone=True,
        )
        self.samsung = cenario.produto().marca
        self.venda_ana = self._venda('Ana', [])
        self.venda_bia = self._venda('Bia', [self.iphone], so_extra=True)
        self.venda_caio = self._venda('Caio', [self.iphone])

    def _venda(self, nome, extras, so_extra=False):
        cliente = cenario.criar_cliente(self.loja, nome)
        venda = cenario.criar_venda(self.loja, cliente)
        if so_extra:
            ProdutoVenda.objects.filter(venda=venda).delete()
        for produto in extras:
            ProdutoVenda.objects.create(
                venda=venda, produto=produto, valor_unitario=produto.valor, quantidade=1, loja=self.loja,
            )
        analise = cenario.criar_analise(cliente, status='A', venda=venda)
        AnaliseCreditoCliente.objects.filter(pk=analise.pk).update(produto=(extras or [cenario.produto()])[-1])
        return venda


class FiltroMarcaVendasTests(CenarioMarcas):
    def _ids(self, filtros):
        return sorted(v.pk for v in vendas.consultar(filtros, escopo_total()))

    def test_filtra_por_marca(self):
        self.assertEqual(self._ids({'marcas': [self.apple]}), sorted([self.venda_bia.pk, self.venda_caio.pk]))
        self.assertEqual(self._ids({'marcas': [self.samsung]}), sorted([self.venda_ana.pk, self.venda_caio.pk]))

    def test_somente_iphone(self):
        self.assertEqual(self._ids({'iphone': True}), sorted([self.venda_bia.pk, self.venda_caio.pk]))

    def test_sem_iphone_exclui_venda_que_tem_algum_iphone(self):
        self.assertEqual(self._ids({'iphone': False}), [self.venda_ana.pk])

    def test_sem_filtro_traz_todas(self):
        self.assertEqual(len(self._ids({'iphone': None})), 3)


class FiltroMarcaSolicitacoesTests(CenarioMarcas):
    def _clientes(self, filtros):
        return sorted(c.nome for c in solicitacoes.consultar(filtros, escopo_total()))

    def test_filtra_por_marca_e_iphone_do_produto_da_solicitacao(self):
        self.assertEqual(self._clientes({'marcas': [self.apple]}), ['Bia', 'Caio'])
        self.assertEqual(self._clientes({'iphone': True}), ['Bia', 'Caio'])
        self.assertEqual(self._clientes({'iphone': False}), ['Ana'])


class FiltrosNoCatalogoTests(CenarioMarcas):
    def test_serializers_validam_e_descrevem_marca_e_iphone(self):
        for classe in (FiltrosVendasSerializer, FiltrosSolicitacoesSerializer):
            filtros = classe(data={'marcas': [self.apple.pk], 'iphone': 'true'}, lojas=Loja.objects.all())
            self.assertTrue(filtros.is_valid(), filtros.errors)
            self.assertEqual(filtros.validated_data['marcas'], [self.apple])
            self.assertIs(filtros.validated_data['iphone'], True)

            campos = {c['nome']: c for c in descrever_filtros(classe(lojas=Loja.objects.all()))}
            self.assertIn({'valor': self.apple.pk, 'rotulo': 'Apple'}, campos['marcas']['opcoes'])
            self.assertEqual(
                [o['rotulo'] for o in campos['iphone']['opcoes']], ['Somente iPhone', 'Sem iPhone'],
            )
