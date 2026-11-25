"""Uma cobrança para várias parcelas e para a quitação com desconto: geração, baixa, API pública e backoffice."""
import hashlib
import json
from decimal import Decimal

from backoffice_api.tests.fabricas import cliente_logado, criar_usuario
from vendas.models import ComprovanteParcela, Pagamento
from vendas.services.erros import ErroDeNegocio

from pagamentos_online.models import Cobranca
from pagamentos_online.servicos.cobrancas import gerar_cobranca_de_parcelas, gerar_quitacao
from pagamentos_online.servicos.planos import plano_de_quitacao

from .base import TOKEN, PagamentoOnlineTestCase, pedido_pago, resposta_pix

PIX = Cobranca.Forma.PIX
CLIENTE = Cobranca.Origem.CLIENTE


def _pix(corpo):
    return resposta_pix(corpo['reference_id'])


class ComDesconto(PagamentoOnlineTestCase):
    def setUp(self):
        super().setUp()
        Pagamento.objects.filter(pk=self.pagamento.pk).update(porcentagem_desconto=Decimal('10'))
        self.pagamento.refresh_from_db()

    def notificar(self, corpo: dict):
        bruto = json.dumps(corpo).encode()
        assinatura = hashlib.sha256(f'{TOKEN}-'.encode() + bruto).hexdigest()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post('/api/pagbank/notificacao/', data=bruto, content_type='application/json',
                                    HTTP_X_AUTHENTICITY_TOKEN=assinatura)

    def pagar(self, cobranca: Cobranca, centavos: int):
        with self.pagbank((200, pedido_pago(str(cobranca.referencia), centavos))):
            self.notificar({'id': 'ORDE_1'})
        for parcela in self.parcelas:
            parcela.refresh_from_db()
        cobranca.refresh_from_db()


class PlanoTest(ComDesconto):
    def test_quitacao_distribui_o_desconto_e_a_ultima_absorve_o_arredondamento(self):
        self.parcelas[0].valor = Decimal('100.01')
        plano = plano_de_quitacao(self.pagamento, self.parcelas)
        self.assertEqual(plano.total_sem_desconto, Decimal('300.01'))
        self.assertEqual(plano.valor, Decimal('270.01'))
        self.assertEqual(sum(i.valor + i.desconto for i in plano.itens), Decimal('300.01'))


class GerarTest(ComDesconto):
    def test_varias_parcelas_viram_uma_cobranca_com_itens(self):
        ids = [self.parcelas[1].pk, self.parcelas[0].pk]
        with self.pagbank((201, _pix)) as simulado:
            cobranca = gerar_cobranca_de_parcelas(self.pagamento, ids, PIX, CLIENTE)
        enviado = simulado.call_args.kwargs['json']
        self.assertEqual(enviado['charges'][0]['amount']['value'], 20000)
        self.assertIn('Parcelas 1 e 2', enviado['items'][0]['name'])
        self.assertEqual(cobranca.tipo, Cobranca.Tipo.PARCELAS)
        self.assertEqual(cobranca.parcela, self.parcelas[0])
        self.assertEqual(cobranca.numeros_das_parcelas(), [1, 2])

    def test_mesmas_parcelas_reaproveitam_a_cobranca_pendente(self):
        ids = [self.parcelas[0].pk, self.parcelas[1].pk]
        with self.pagbank((201, _pix)):
            primeira = gerar_cobranca_de_parcelas(self.pagamento, ids, PIX, CLIENTE)
        with self.pagbank() as simulado:
            segunda = gerar_cobranca_de_parcelas(self.pagamento, list(reversed(ids)), PIX, CLIENTE)
        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(simulado.call_count, 0)

    def test_recusa_parcela_paga_ou_de_outra_compra(self):
        self.parcelas[1].pago = True
        self.parcelas[1].save()
        with self.assertRaisesMessage(ErroDeNegocio, 'A parcela 2 já está paga.'):
            gerar_cobranca_de_parcelas(self.pagamento, [self.parcelas[0].pk, self.parcelas[1].pk], PIX, CLIENTE)
        with self.assertRaisesMessage(ErroDeNegocio, 'Parcela não encontrada'):
            gerar_cobranca_de_parcelas(self.pagamento, [self.parcelas[0].pk, 999999], PIX, CLIENTE)

    def test_quitacao_cobra_o_total_com_desconto(self):
        with self.pagbank((201, _pix)) as simulado:
            cobranca = gerar_quitacao(self.pagamento, PIX, CLIENTE)
        self.assertEqual(simulado.call_args.kwargs['json']['charges'][0]['amount']['value'], 27000)
        self.assertEqual(cobranca.tipo, Cobranca.Tipo.QUITACAO)
        self.assertEqual(cobranca.itens.count(), 3)

    def test_taxa_do_cartao_incide_sobre_o_total_das_parcelas(self):
        ids = [self.parcelas[0].pk, self.parcelas[1].pk]
        checkout = {'id': 'CHEC_1', 'links': [{'rel': 'PAY', 'href': 'https://pagar'}]}
        with self.pagbank((201, checkout)):
            cobranca = gerar_cobranca_de_parcelas(self.pagamento, ids, Cobranca.Forma.CARTAO, CLIENTE)
        self.assertEqual(cobranca.valor_parcela, Decimal('200.00'))
        self.assertEqual(cobranca.valor_total, Decimal('210.51'))


class BaixaAgrupadaTest(ComDesconto):
    def test_pagamento_de_varias_parcelas_baixa_todas_e_anexa_o_comprovante_em_cada(self):
        with self.pagbank((201, _pix)):
            cobranca = gerar_cobranca_de_parcelas(self.pagamento, [p.pk for p in self.parcelas[:2]], PIX, CLIENTE)
        self.pagar(cobranca, 20000)
        self.assertTrue(self.parcelas[0].pago and self.parcelas[1].pago)
        self.assertFalse(self.parcelas[2].pago)
        self.assertEqual(cobranca.acerto_manual, '')
        self.assertEqual(ComprovanteParcela.objects.filter(parcela__in=self.parcelas[:2]).count(), 2)

    def test_quitacao_paga_aplica_o_desconto_e_marca_a_compra_quitada(self):
        with self.pagbank((201, _pix)):
            cobranca = gerar_quitacao(self.pagamento, PIX, CLIENTE)
        self.pagar(cobranca, 27000)
        self.pagamento.refresh_from_db()
        self.assertTrue(self.pagamento.quitado)
        self.assertTrue(all(p.pago for p in self.parcelas))
        self.assertEqual([p.valor for p in self.parcelas], [Decimal('90.00')] * 3)
        self.assertEqual(sum(p.valor_pago for p in self.parcelas), Decimal('270.00'))
        self.assertEqual(cobranca.acerto_manual, '')

    def test_quitacao_paga_a_menor_credita_em_ordem_sem_desconto(self):
        with self.pagbank((201, _pix)):
            cobranca = gerar_quitacao(self.pagamento, PIX, CLIENTE)
        self.pagar(cobranca, 15000)
        self.pagamento.refresh_from_db()
        self.assertFalse(self.pagamento.quitado)
        self.assertTrue(self.parcelas[0].pago)
        self.assertEqual(self.parcelas[0].valor, Decimal('100.00'))
        self.assertEqual(self.parcelas[1].valor_pago, Decimal('50.00'))
        self.assertIn('desconto da quitação não foi aplicado', cobranca.acerto_manual)

    def test_parcela_paga_no_meio_do_caminho_vira_excedente(self):
        with self.pagbank((201, _pix)):
            cobranca = gerar_cobranca_de_parcelas(self.pagamento, [p.pk for p in self.parcelas[:2]], PIX, CLIENTE)
        self.parcelas[1].pago = True
        self.parcelas[1].save()
        self.pagar(cobranca, 20000)
        self.assertTrue(self.parcelas[0].pago)
        self.assertIn('2 já estava(m) paga(s)', cobranca.acerto_manual)
        self.assertIn('excedente de R$ 100.00', cobranca.acerto_manual)
        self.assertFalse(cobranca.pagamento_duplicado)


class ApiPublicaAgrupadaTest(ComDesconto):
    def url(self, sufixo=''):
        return f'/api/publico/v1/pagamentos/{self.pagamento.token_publico}/{sufixo}'

    def test_detalhe_traz_a_quitacao_com_opcoes_online(self):
        quitacao = self.client.get(self.url()).json()['quitacao']
        self.assertEqual(quitacao['total_com_desconto'], '270.00')
        self.assertEqual(quitacao['valor_desconto'], '30.00')
        self.assertTrue(quitacao['pode_pagar_online'])
        self.assertIsNone(quitacao['pix_estatico'])
        self.assertEqual([o['forma'] for o in quitacao['opcoes']], ['pix', 'boleto', 'cartao'])

    def test_opcoes_de_varias_parcelas_e_da_quitacao(self):
        ids = f'{self.parcelas[0].pk},{self.parcelas[2].pk}'
        dados = self.client.get(self.url(f'opcoes/?parcelas={ids}')).json()
        self.assertEqual(dados['valor'], '200.00')
        self.assertEqual([p['numero'] for p in dados['parcelas']], [1, 3])
        self.assertEqual(self.client.get(self.url('opcoes/?quitacao=1')).json()['valor'], '270.00')
        self.assertEqual(self.client.get(self.url('opcoes/?parcelas=x')).status_code, 400)

    def test_gera_cobranca_de_varias_parcelas_e_ela_aparece_no_detalhe(self):
        corpo = {'forma': 'pix', 'parcelas': [self.parcelas[0].pk, self.parcelas[1].pk]}
        with self.pagbank((201, _pix)):
            resposta = self.client.post(self.url('cobrancas/'), corpo, content_type='application/json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(resposta.json()['tipo'], 'parcelas')
        self.assertEqual([p['numero'] for p in resposta.json()['parcelas']], [1, 2])
        detalhe = self.client.get(self.url()).json()
        self.assertEqual(len(detalhe['cobrancas_agrupadas_pendentes']), 1)
        self.assertIsNone(detalhe['parcelas'][0]['cobranca_pendente'])

    def test_exige_parcelas_ou_quitacao(self):
        for corpo in ({'forma': 'pix'}, {'forma': 'pix', 'quitacao': True, 'parcelas': [self.parcela.pk]}):
            resposta = self.client.post(self.url('cobrancas/'), corpo, content_type='application/json')
            self.assertEqual(resposta.status_code, 400)

    def test_comprovante_da_quitacao(self):
        with self.pagbank((201, _pix)):
            cobranca = gerar_quitacao(self.pagamento, PIX, CLIENTE)
        self.pagar(cobranca, 27000)
        resposta = self.client.get(self.url(f'cobrancas/{cobranca.referencia}/comprovante/'))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('comprovante-quitacao.pdf', resposta['Content-Disposition'])


class BackofficeAgrupadoTest(ComDesconto):
    URL = '/api/bo/v1/cobrancas_online/'

    def setUp(self):
        super().setUp()
        usuario = criar_usuario('ana', grupos=('ANALISTA',), permissoes=('vendas.change_pagamento',
                                'vendas.view_pagamento'), lojas=(self.loja,))
        self.bo = cliente_logado(usuario)

    def test_pix_pendente_traz_a_imagem_do_qr(self):
        with self.pagbank((201, _pix)):
            resposta = self.bo.post(f'{self.URL}parcelas/{self.parcela.pk}/cobrancas/', {'forma': 'pix'},
                                    format='json')
        self.assertTrue(resposta.json()['qr_code_base64'])
        self.assertEqual(resposta.json()['rotulo'], 'Parcela 1')

    def test_gera_quitacao_pela_compra_e_aparece_em_cada_parcela(self):
        url = f'{self.URL}pagamentos/{self.pagamento.pk}/cobrancas/'
        self.assertEqual(self.bo.get(url).json()['quitacao']['valor'], '270.00')
        with self.pagbank((201, _pix)):
            resposta = self.bo.post(url, {'forma': 'pix', 'quitacao': True}, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(resposta.json()['rotulo'], 'Quitação')
        self.assertEqual(len(resposta.json()['itens']), 3)
        da_parcela = self.bo.get(f'{self.URL}parcelas/{self.parcelas[2].pk}/cobrancas/').json()['cobrancas']
        self.assertEqual([c['tipo'] for c in da_parcela], ['quitacao'])

    def test_opcoes_antes_de_gerar(self):
        ids = f'{self.parcelas[0].pk},{self.parcelas[1].pk}'
        dados = self.bo.get(f'{self.URL}pagamentos/{self.pagamento.pk}/opcoes/?parcelas={ids}').json()
        self.assertEqual(dados['valor'], '200.00')
