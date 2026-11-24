import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.utils import timezone

from vendas.models import ComprovanteParcela

from pagamentos_online.models import Cobranca
from pagamentos_online.servicos.cobrancas import gerar_cobranca
from pagamentos_online.servicos.conciliacao import conciliar

from .base import TOKEN, PagamentoOnlineTestCase, pedido_pago, resposta_pix

URL = '/api/pagbank/notificacao/'


def _assinar(corpo: bytes) -> str:
    return hashlib.sha256(f'{TOKEN}-'.encode() + corpo).hexdigest()


class ComCobrancaPix(PagamentoOnlineTestCase):
    def setUp(self):
        super().setUp()
        with self.pagbank((201, lambda corpo: resposta_pix(corpo['reference_id']))):
            self.cobranca = gerar_cobranca(self.parcela, Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        self.referencia = str(self.cobranca.referencia)

    def notificar(self, corpo: dict, assinatura: str | None = None, **cabecalhos):
        bruto = json.dumps(corpo).encode()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                URL, data=bruto, content_type='application/json',
                HTTP_X_AUTHENTICITY_TOKEN=assinatura if assinatura is not None else _assinar(bruto),
                **{f'HTTP_{k.upper().replace("-", "_")}': v for k, v in cabecalhos.items()},
            )


class BaixaTest(ComCobrancaPix):
    def test_notificacao_valida_consulta_o_pedido_e_da_baixa_com_comprovante(self):
        pago = pedido_pago(self.referencia, 10000)
        with self.pagbank((200, pago)) as simulado:
            resposta = self.notificar({'id': 'ORDE_1', 'charges': [{'status': 'PAID'}]})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(simulado.call_args.args[1].endswith('/orders/ORDE_1'))
        self.parcela.refresh_from_db()
        self.cobranca.refresh_from_db()
        self.assertTrue(self.parcela.pago)
        self.assertEqual(self.parcela.valor_pago, Decimal('100.00'))
        self.assertEqual(self.parcela.origem_baixa, 'pagbank')
        self.assertEqual(self.cobranca.status, Cobranca.Status.PAGA)
        self.assertEqual(self.cobranca.detalhes_pagamento['end_to_end_id'], 'E123')
        comprovante = ComprovanteParcela.objects.get(parcela=self.parcela)
        self.assertTrue(comprovante.arquivo.name.endswith('.pdf'))

    def test_mesmo_pagamento_duas_vezes_nao_da_baixa_em_dobro(self):
        pago = pedido_pago(self.referencia, 10000)
        with self.pagbank((200, pago), (200, pago)):
            self.notificar({'id': 'ORDE_1'})
            self.notificar({'id': 'ORDE_1'})
        self.parcela.refresh_from_db()
        self.assertEqual(self.parcela.valor_pago, Decimal('100.00'))
        self.assertEqual(ComprovanteParcela.objects.filter(parcela=self.parcela).count(), 1)

    def test_assinatura_invalida_e_recusada_sem_consultar_nem_dar_baixa(self):
        with self.pagbank() as simulado:
            resposta = self.notificar({'id': 'ORDE_1'}, assinatura='falsa')
        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(simulado.call_count, 0)
        self.parcela.refresh_from_db()
        self.assertFalse(self.parcela.pago)

    def test_corpo_falso_nao_basta_o_que_vale_e_a_consulta(self):
        with self.pagbank((200, resposta_pix(self.referencia))):
            self.notificar({'id': 'ORDE_1', 'charges': [{'status': 'PAID'}]})
        self.parcela.refresh_from_db()
        self.assertFalse(self.parcela.pago)

    def test_parcela_ja_paga_marca_pagamento_em_duplicidade(self):
        self.parcela.pago = True
        self.parcela.save()
        with self.pagbank((200, pedido_pago(self.referencia, 10000))):
            self.notificar({'id': 'ORDE_1'})
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, Cobranca.Status.PAGA)
        self.assertTrue(self.cobranca.pagamento_duplicado)

    def test_pagbank_fora_do_ar_responde_503_para_reenviar(self):
        with self.pagbank((500, {})):
            resposta = self.notificar({'id': 'ORDE_1'})
        self.assertEqual(resposta.status_code, 503)

    def test_checkout_de_cartao_e_localizado_pelo_id_do_checkout(self):
        cartao = Cobranca.objects.create(
            parcela=self.parcelas[1], forma=Cobranca.Forma.CARTAO, origem=Cobranca.Origem.CLIENTE,
            valor_parcela=Decimal('100.00'), taxa=Decimal('5.26'), valor_total=Decimal('105.26'),
            pagbank_id='CHEC_9', link_pagamento='https://pag', expira_em=timezone.now() + timedelta(hours=1),
        )
        pago = pedido_pago('referencia-desconhecida', 10526, pedido_id='ORDE_9', tipo='CREDIT_CARD')
        with self.pagbank((200, pago)):
            self.notificar({'id': 'ORDE_9'}, **{'x-product-id': 'CHEC_9'})
        cartao.refresh_from_db()
        self.assertEqual(cartao.status, Cobranca.Status.PAGA)

    def test_falha_no_aviso_nao_quebra_a_baixa(self):
        with mock.patch('pagamentos_online.servicos.avisos.notificar_grupos', side_effect=RuntimeError):
            with self.pagbank((200, pedido_pago(self.referencia, 10000))):
                resposta = self.notificar({'id': 'ORDE_1'})
        self.assertEqual(resposta.status_code, 200)
        self.parcela.refresh_from_db()
        self.assertTrue(self.parcela.pago)


class ConciliacaoTest(ComCobrancaPix):
    def test_conciliacao_consulta_pendentes_e_da_baixa(self):
        antigo = timezone.now() - timedelta(minutes=10)
        Cobranca.objects.filter(pk=self.cobranca.pk).update(criado_em=antigo, atualizado_em=antigo)
        with self.pagbank((200, pedido_pago(self.referencia, 10000))):
            resultado = conciliar()
        self.assertEqual(resultado['consultadas'], 1)
        self.parcela.refresh_from_db()
        self.assertTrue(self.parcela.pago)

    def test_conciliacao_expira_cobranca_vencida(self):
        vencida = timezone.now() - timedelta(hours=3)
        Cobranca.objects.filter(pk=self.cobranca.pk).update(expira_em=vencida, atualizado_em=timezone.now())
        with self.pagbank():
            resultado = conciliar()
        self.assertEqual(resultado['expiradas'], 1)
        self.cobranca.refresh_from_db()
        self.assertEqual(self.cobranca.status, Cobranca.Status.EXPIRADA)
