"""Consulta do assistente: parcelas já pagas (com a data), compras quitadas e ordem das compras."""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from crm.services.assistente import consulta_parcelas
from crm.tests.test_assistente import IDENTIDADE_CERTA, AssistenteBase, ferramenta, texto
from vendas.models import Pagamento, Parcela, TipoPagamento, Venda


class ConsultaParcelasTests(AssistenteBase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.pagas = Parcela.objects.filter(pagamento=self.pagamento, pago=True)
        self.pagas.update(data_pagamento=self.hoje - timedelta(days=38))

    def _compra_quitada(self) -> Pagamento:
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.atendente, loja=self.loja,
                                     repasse_logista=Decimal('100.00'))
        pagamento = Pagamento.objects.create(venda=venda, tipo_pagamento=TipoPagamento.objects.get(nome='IPX'),
                                             valor=Decimal('200.00'), parcelas=2, loja=self.loja,
                                             data_primeira_parcela=date.today())
        Parcela.objects.filter(pagamento=pagamento).update(pago=True, data_pagamento=date(2026, 3, 10))
        Parcela.objects.filter(pagamento=pagamento, numero_parcela=2).update(data_pagamento=date(2026, 4, 12))
        return pagamento

    def test_compra_em_andamento_traz_pagas_com_data_e_abertas(self):
        compra = consulta_parcelas.consultar([self.cliente], self.hoje)['compras'][0]

        self.assertEqual((compra['situacao'], compra['parcelas_pagas'], compra['total_parcelas']), ('em andamento', 1, 3))
        self.assertEqual(compra['total_pago'], 'R$ 100,00')
        paga = compra['parcelas_pagas_recentes'][0]
        self.assertEqual((paga['numero'], paga['pago_em']), (1, (self.hoje - timedelta(days=38)).strftime('%d/%m/%Y')))
        self.assertEqual([p['situacao'] for p in compra['parcelas']], ['atrasada', 'a vencer'])

    def test_compra_quitada_aparece_depois_das_em_andamento_com_a_data_da_quitacao(self):
        quitada = self._compra_quitada()

        compras = consulta_parcelas.consultar([self.cliente], self.hoje)['compras']

        self.assertEqual([c['situacao'] for c in compras], ['em andamento', 'quitada'])
        self.assertEqual(compras[1]['quitada_em'], '12/04/2026')
        self.assertEqual((compras[1]['parcelas_pagas'], compras[1]['total_parcelas']), (2, 2))
        self.assertNotIn('parcelas', compras[1])  # nada a pagar: sem parcela_id para gerar link
        self.assertTrue(Pagamento.objects.filter(pk=quitada.pk).exists())

    def test_so_quitadas_avisa_que_nao_ha_nada_em_aberto(self):
        Parcela.objects.filter(pagamento=self.pagamento).update(pago=True)

        resultado = consulta_parcelas.consultar([self.cliente], self.hoje)

        self.assertEqual(resultado['compras'][0]['situacao'], 'quitada')
        self.assertIn('todas as compras estão quitadas', resultado['observacao'])
        self.assertEqual(resultado['compras'][0]['parcelas_pagas_recentes'][-1]['pago_em'], 'data não registrada')

    def test_entrada_nao_entra_na_consulta(self):
        entrada = TipoPagamento.objects.create(nome='ENTRADA', caixa=True)
        Pagamento.objects.create(venda=self.pagamento.venda, tipo_pagamento=entrada, valor=Decimal('200.00'),
                                 parcelas=1, loja=self.loja, data_primeira_parcela=date.today())

        compras = consulta_parcelas.consultar([self.cliente], self.hoje)['compras']

        self.assertEqual(len(compras), 1)
        self.assertEqual(compras[0]['total_parcelas'], 3)

    def test_ferramenta_do_bot_devolve_o_historico(self):
        self._compra_quitada()
        roteiro = self.com_roteiro(
            ferramenta('identificar_cliente', IDENTIDADE_CERTA),
            ferramenta('consultar_parcelas', {}, 'tu_2'),
            texto('Sua compra anterior foi quitada em 12/04/2026.'),
        )

        self.receber('cpf 529.982.247-25 nascimento 17/05/1990, quando quitei minha compra?', wamid='w1')

        consulta = json.loads(roteiro.resultado(2)['content'])
        self.assertEqual([c['situacao'] for c in consulta['compras']], ['em andamento', 'quitada'])
