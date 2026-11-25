from decimal import Decimal

from vendas.services.erros import ErroDeNegocio

from pagamentos_online.models import Cobranca, RegistroPagBank
from pagamentos_online.servicos.cobrancas import gerar_cobranca, opcoes_da_parcela

from .base import PagamentoOnlineTestCase, resposta_pix

Forma = Cobranca.Forma
Origem = Cobranca.Origem


def _ecoar_pix(corpo):
    return resposta_pix(corpo['reference_id'])


class OpcoesTest(PagamentoOnlineTestCase):
    def test_pix_sem_taxa_e_boleto_e_cartao_com_a_taxa_do_cliente(self):
        opcoes = {o.forma: o for o in opcoes_da_parcela(self.parcela)}
        self.assertEqual(opcoes['pix'].total, Decimal('100.00'))
        self.assertEqual(opcoes['boleto'].total, Decimal('103.49'))
        self.assertEqual(opcoes['cartao'].total, Decimal('105.26'))
        self.assertEqual(opcoes['cartao'].max_parcelas_cartao, 12)

    def test_sem_opcoes_quando_desligado_ou_parcela_paga(self):
        self.configuracao.ativo = False
        self.configuracao.save()
        self.assertEqual(opcoes_da_parcela(self.parcela), [])
        self.configuracao.ativo = True
        self.configuracao.save()
        self.parcela.pago = True
        self.parcela.save()
        self.assertEqual(opcoes_da_parcela(self.parcela), [])


class GerarCobrancaTest(PagamentoOnlineTestCase):
    def test_gera_pix_com_o_valor_do_banco_e_o_endereco_de_notificacao(self):
        with self.pagbank((201, _ecoar_pix)) as simulado:
            cobranca = gerar_cobranca(self.parcela, Forma.PIX, Origem.BOT)
        corpo = simulado.call_args.kwargs['json']
        self.assertEqual(corpo['charges'][0]['amount']['value'], 10000)
        self.assertEqual(corpo['charges'][0]['payment_method']['type'], 'PIX')
        self.assertEqual(corpo['notification_urls'], ['https://credfacil.exemplo.com/api/pagbank/notificacao/'])
        self.assertEqual(corpo['customer']['email'], 'cobranca@exemplo.com')
        self.assertEqual(simulado.call_args.kwargs['headers']['Authorization'], 'Bearer token-de-teste')
        self.assertEqual(cobranca.pagbank_id, 'ORDE_1')
        self.assertTrue(cobranca.pix_copia_cola.startswith('000201'))
        self.assertEqual(cobranca.status, Cobranca.Status.PENDENTE)
        registro = RegistroPagBank.objects.get()
        self.assertNotIn('token-de-teste', str(registro.requisicao) + str(registro.resposta))

    def test_reaproveita_a_cobranca_pendente_em_vez_de_criar_outra(self):
        with self.pagbank((201, _ecoar_pix)) as simulado:
            primeira = gerar_cobranca(self.parcela, Forma.PIX, Origem.CLIENTE)
            segunda = gerar_cobranca(self.parcela, Forma.PIX, Origem.BOT)
        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(simulado.call_count, 1)

    def test_boleto_soma_a_tarifa_e_manda_endereco_com_uf_padrao(self):
        resposta = {'id': 'ORDE_2', 'charges': [{
            'payment_method': {'boleto': {'formatted_barcode': '0339 1234'}},
            'links': [{'rel': 'SELF', 'media': 'application/pdf', 'href': 'https://boleto.pagseguro.com.br/x.pdf'}],
        }]}
        with self.pagbank((201, resposta)) as simulado:
            cobranca = gerar_cobranca(self.parcela, Forma.BOLETO, Origem.CLIENTE)
        corpo = simulado.call_args.kwargs['json']
        boleto = corpo['charges'][0]['payment_method']['boleto']
        self.assertEqual(corpo['charges'][0]['amount']['value'], 10349)
        self.assertEqual(boleto['holder']['address']['region_code'], 'PA')
        self.assertEqual(cobranca.taxa, Decimal('3.49'))
        self.assertEqual(cobranca.boleto_pdf_url, 'https://boleto.pagseguro.com.br/x.pdf')

    def test_cartao_usa_checkout_so_com_credito_e_limite_de_parcelas(self):
        resposta = {'id': 'CHEC_1', 'links': [{'rel': 'PAY', 'href': 'https://pagamento.pagbank.com.br/p?code=1'}]}
        with self.pagbank((201, resposta)) as simulado:
            cobranca = gerar_cobranca(self.parcela, Forma.CARTAO, Origem.CLIENTE)
        url = simulado.call_args.args[1]
        corpo = simulado.call_args.kwargs['json']
        self.assertTrue(url.endswith('/checkouts'))
        self.assertEqual(corpo['payment_methods'], [{'type': 'CREDIT_CARD'}])
        self.assertEqual(corpo['payment_methods_configs'][0]['config_options'][0]['value'], '12')
        self.assertNotIn('INTEREST_FREE_INSTALLMENTS', str(corpo))
        self.assertEqual(corpo['items'][0]['unit_amount'], 10526)
        self.assertEqual(cobranca.link_pagamento, 'https://pagamento.pagbank.com.br/p?code=1')
        self.assertEqual(corpo['customer']['tax_id'], self.pagamento.venda.cliente.cpf)
        self.assertEqual(corpo['customer']['email'], 'cobranca@exemplo.com')
        self.assertNotIn('phones', corpo['customer'])

    def test_recusa_do_pagbank_cancela_a_cobranca_e_mostra_mensagem_amigavel(self):
        with self.pagbank((400, {'error_messages': [{'description': 'invalid tax_id'}]})):
            with self.assertRaises(ErroDeNegocio) as erro:
                gerar_cobranca(self.parcela, Forma.PIX, Origem.CLIENTE)
        self.assertIn('Tente de novo', erro.exception.mensagem)
        self.assertEqual(Cobranca.objects.get().status, Cobranca.Status.CANCELADA)

    def test_recusa_parcela_paga_forma_desligada_e_cliente_sem_email(self):
        self.configuracao.boleto_ativo = False
        self.configuracao.email_padrao = ''
        self.configuracao.save()
        with self.assertRaises(ErroDeNegocio):
            gerar_cobranca(self.parcela, Forma.BOLETO, Origem.CLIENTE)
        with self.assertRaises(ErroDeNegocio) as sem_email:
            gerar_cobranca(self.parcela, Forma.PIX, Origem.CLIENTE)
        self.assertIn('e-mail', sem_email.exception.mensagem)
        self.parcela.pago = True
        self.parcela.save()
        with self.assertRaises(ErroDeNegocio):
            gerar_cobranca(self.parcela, Forma.PIX, Origem.CLIENTE)
        self.assertFalse(Cobranca.objects.exists())

    def test_sem_token_no_servidor_nao_gera(self):
        with self.settings(PAGBANK_TOKEN=''):
            with self.assertRaises(ErroDeNegocio):
                gerar_cobranca(self.parcela, Forma.PIX, Origem.CLIENTE)
