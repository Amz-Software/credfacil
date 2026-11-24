from decimal import Decimal

from django.test import SimpleTestCase

from pagamentos_online.taxas import total_boleto, total_cartao, total_pix


class TaxasTest(SimpleTestCase):
    def test_pix_nao_tem_taxa(self):
        self.assertEqual(total_pix(Decimal('150.00')), (Decimal('150.00'), Decimal('0.00')))

    def test_boleto_soma_a_tarifa_fixa(self):
        self.assertEqual(total_boleto(Decimal('150.00'), Decimal('3.49')), (Decimal('153.49'), Decimal('3.49')))

    def test_cartao_calcula_por_dentro_para_empresa_receber_o_valor_cheio(self):
        total, taxa = total_cartao(Decimal('150.00'), Decimal('4.99'))
        self.assertEqual(total, Decimal('157.88'))
        self.assertEqual(taxa, Decimal('7.88'))
        self.assertGreaterEqual(total - (total * Decimal('4.99') / 100), Decimal('150.00'))

    def test_cartao_sem_taxa_configurada_cobra_o_valor_da_parcela(self):
        self.assertEqual(total_cartao(Decimal('99.90'), Decimal('0')), (Decimal('99.90'), Decimal('0.00')))

    def test_percentual_invalido_e_recusado(self):
        with self.assertRaises(ValueError):
            total_cartao(Decimal('100'), Decimal('100'))
