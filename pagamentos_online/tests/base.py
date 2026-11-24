"""Base dos testes: PagBank simulado (nenhuma chamada sai para a rede), tarefas síncronas, conta com parcelas."""
import shutil
import tempfile
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from backoffice_api.financeiro.tests.fabricas import criar_conta, parcelas_de
from backoffice_api.tests.fabricas import criar_loja
from crm.models import ConfiguracaoCRM
from pagamentos_online.models import ConfiguracaoPagamentoOnline

TOKEN = 'token-de-teste'


def resposta_pix(referencia: str, pedido_id: str = 'ORDE_1') -> dict:
    return {
        'id': pedido_id, 'reference_id': referencia,
        'charges': [{
            'id': 'CHAR_1', 'reference_id': referencia, 'status': 'WAITING',
            'qr_code': {'id': 'QRCO_1', 'text': '00020101021226850014br.gov.bcb.pix-copia-e-cola'},
            'links': [{'rel': 'QRCODE.PNG', 'href': 'https://sandbox.api.pagseguro.com/qrcode/QRCO_1/png'}],
        }],
    }


def pedido_pago(referencia: str, valor_centavos: int, pedido_id: str = 'ORDE_1', tipo: str = 'PIX') -> dict:
    return {
        'id': pedido_id, 'reference_id': referencia,
        'charges': [{
            'id': 'CHAR_1', 'reference_id': referencia, 'status': 'PAID',
            'paid_at': '2026-11-24T10:00:00-03:00',
            'amount': {'value': valor_centavos, 'summary': {'total': valor_centavos, 'paid': valor_centavos}},
            'payment_method': {'type': tipo, 'pix': {'end_to_end_id': 'E123'}},
        }],
    }


class RespostaFalsa:
    def __init__(self, status_code: int, corpo: dict):
        self.status_code = status_code
        self._corpo = corpo
        self.text = str(corpo)

    def json(self):
        return self._corpo


@override_settings(PAGBANK_TOKEN=TOKEN, PAGBANK_AMBIENTE='sandbox', CRM_TAREFAS_SINCRONAS=True,
                   NOTIFICACAO_WS_SINCRONO=False)
class PagamentoOnlineTestCase(TestCase):
    def setUp(self):
        self.pasta_midia = tempfile.mkdtemp(prefix='pagamentos-online-')
        self.addCleanup(shutil.rmtree, self.pasta_midia, ignore_errors=True)
        midia = override_settings(MEDIA_ROOT=self.pasta_midia)
        midia.enable()
        self.addCleanup(midia.disable)
        self.loja = criar_loja()
        self.pagamento = criar_conta(self.loja, valor='300.00', parcelas=3)
        self.parcelas = parcelas_de(self.pagamento)
        self.parcela = self.parcelas[0]
        configuracao_crm = ConfiguracaoCRM.obter()
        configuracao_crm.url_publica = 'https://credfacil.exemplo.com'
        configuracao_crm.save()
        self.configuracao = ConfiguracaoPagamentoOnline.obter()
        self.configuracao.ativo = True
        self.configuracao.boleto_ativo = True
        self.configuracao.cartao_ativo = True
        self.configuracao.taxa_boleto = Decimal('3.49')
        self.configuracao.taxa_cartao_percentual = Decimal('4.99')
        self.configuracao.email_padrao = 'cobranca@exemplo.com'
        self.configuracao.url_app_cliente = 'https://vendas.exemplo.com'
        self.configuracao.save()

    @contextmanager
    def pagbank(self, *respostas):
        """Simula as respostas HTTP do PagBank, na ordem; devolve o mock para conferir as chamadas."""
        fila = list(respostas)

        def responder(metodo, url, **kwargs):
            status_code, corpo = fila.pop(0)
            return RespostaFalsa(status_code, corpo(kwargs.get('json')) if callable(corpo) else corpo)

        with mock.patch('pagamentos_online.pagbank.cliente.requests.request', side_effect=responder) as simulado:
            yield simulado
