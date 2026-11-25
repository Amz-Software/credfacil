"""Testes de ponta a ponta contra o sandbox REAL do PagBank (rede de verdade).

Só rodam com PAGBANK_SANDBOX_E2E=1, PAGBANK_AMBIENTE=sandbox e PAGBANK_TOKEN de sandbox no ambiente:

    PAGBANK_SANDBOX_E2E=1 DB_USED=sqlite python manage.py test pagamentos_online.tests.test_sandbox_e2e

O simulador do sandbox decide pelo valor: Pix/boleto até R$ 100,00 é pago na hora. Por isso a conta tem
parcelas de R$ 30,00. Dados do comprador são fictícios. As chamadas trocadas (para a homologação) são
gravadas em JSON na pasta de PAGBANK_SANDBOX_SAIDA (padrão: diretório temporário).
"""
import json
import os
import shutil
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from unittest import mock

from django.test import LiveServerTestCase, TestCase, override_settings
from django.utils import timezone

from backoffice_api.financeiro.tests.fabricas import criar_conta, parcelas_de
from backoffice_api.tests.fabricas import criar_loja
from crm.models import ConfiguracaoCRM
from pagamentos_online.models import Cobranca, ConfiguracaoPagamentoOnline, RegistroPagBank
from pagamentos_online.pagbank import cliente
from pagamentos_online.servicos.baixa import processar_pedido
from pagamentos_online.servicos.cobrancas import (
    gerar_cobranca, gerar_cobranca_de_parcelas, gerar_quitacao,
)
from vendas.models import ComprovanteParcela, Pagamento

LIGADO = os.environ.get('PAGBANK_SANDBOX_E2E') == '1'
CPF_TESTE = '11144477735'  # CPF válido de teste (o 529.982.247-25 o sandbox trata como do vendedor)
ESPERA_PAGAMENTO = 60  # segundos


class CenarioSandbox:
    """Conta de R$ 90,00 em 3 parcelas, 10% de desconto na quitação, comprador fictício."""

    def montar_cenario(self):
        pasta = tempfile.mkdtemp(prefix='pagbank-sandbox-')
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        midia = override_settings(MEDIA_ROOT=pasta)
        midia.enable()
        self.addCleanup(midia.disable)
        self.addCleanup(self._salvar_registros)
        loja = criar_loja()
        self.pagamento = criar_conta(loja, valor='90.00', parcelas=3, nome='Comprador Teste Sandbox', cpf=CPF_TESTE)
        Pagamento.objects.filter(pk=self.pagamento.pk).update(porcentagem_desconto=Decimal('10'))
        self.pagamento.refresh_from_db()
        self.parcelas = parcelas_de(self.pagamento)
        crm = ConfiguracaoCRM.obter()
        crm.url_publica = os.environ.get('PAGBANK_SANDBOX_URL_PUBLICA', 'https://credfacil.exemplo.com.br')
        crm.save()
        configuracao = ConfiguracaoPagamentoOnline.obter()
        configuracao.ativo = configuracao.boleto_ativo = configuracao.cartao_ativo = True
        configuracao.taxa_boleto = Decimal('3.49')
        configuracao.taxa_cartao_percentual = Decimal('4.99')
        configuracao.email_padrao = 'comprador.teste@exemplo.com.br'
        configuracao.url_app_cliente = 'https://vendas.exemplo.com.br'
        configuracao.save()

    def _salvar_registros(self):
        destino = Path(os.environ.get('PAGBANK_SANDBOX_SAIDA') or tempfile.gettempdir())
        destino.mkdir(parents=True, exist_ok=True)
        registros = [{
            'tipo': r.tipo, 'metodo': r.metodo, 'caminho': r.caminho, 'status_http': r.status_http,
            'requisicao': r.requisicao, 'resposta': r.resposta, 'criado_em': r.criado_em.isoformat(),
        } for r in RegistroPagBank.objects.order_by('id')]
        arquivo = destino / f'{self._testMethodName}.json'
        arquivo.write_text(json.dumps(registros, ensure_ascii=False, indent=2))

@unittest.skipUnless(LIGADO, 'Defina PAGBANK_SANDBOX_E2E=1 para testar no sandbox real do PagBank.')
@override_settings(CRM_TAREFAS_SINCRONAS=True, NOTIFICACAO_WS_SINCRONO=False, CRM_CACHE_LIMITES='default')
class SandboxPagBankE2E(CenarioSandbox, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if settings.PAGBANK_AMBIENTE != 'sandbox' or not settings.PAGBANK_TOKEN:
            raise unittest.SkipTest('Exige PAGBANK_AMBIENTE=sandbox e PAGBANK_TOKEN de sandbox.')

    def setUp(self):
        self.montar_cenario()

    def esperar_pagamento(self, cobranca: Cobranca) -> Cobranca:
        """Consulta o pedido até o simulador marcar como pago e processa como a conciliação faz."""
        limite = time.monotonic() + ESPERA_PAGAMENTO
        while time.monotonic() < limite:
            pedido = cliente.consultar_pedido(cobranca.pagbank_id, cobranca=cobranca)
            if any(c.get('status') == 'PAID' for c in pedido.get('charges') or []):
                with self.captureOnCommitCallbacks(execute=True):
                    processar_pedido(pedido)
                cobranca.refresh_from_db()
                return cobranca
            time.sleep(3)
        self.fail(f'O sandbox não marcou o pedido {cobranca.pagbank_id} como pago em {ESPERA_PAGAMENTO}s.')

    def recarregar(self):
        for parcela in self.parcelas:
            parcela.refresh_from_db()
        self.pagamento.refresh_from_db()

    def test_1_pix_de_uma_parcela_gera_paga_e_da_baixa(self):
        cobranca = gerar_cobranca(self.parcelas[0], Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        self.assertTrue(cobranca.pagbank_id.startswith('ORDE_'))
        self.assertTrue(cobranca.pix_copia_cola.startswith('000201'))
        self.assertEqual(cobranca.valor_total, Decimal('30.00'))
        cobranca = self.esperar_pagamento(cobranca)
        self.recarregar()
        self.assertEqual(cobranca.status, Cobranca.Status.PAGA)
        self.assertEqual(cobranca.valor_pago, Decimal('30.00'))
        self.assertTrue(self.parcelas[0].pago)
        self.assertEqual(self.parcelas[0].origem_baixa, 'pagbank')
        self.assertTrue(ComprovanteParcela.objects.filter(parcela=self.parcelas[0]).exists())

    def test_2_boleto_tem_linha_digitavel_pdf_e_taxa(self):
        cobranca = gerar_cobranca(self.parcelas[0], Cobranca.Forma.BOLETO, Cobranca.Origem.BACKOFFICE)
        self.assertTrue(cobranca.boleto_linha_digitavel)
        self.assertTrue(cobranca.boleto_pdf_url.startswith('https://'))
        self.assertEqual(cobranca.valor_total, Decimal('33.49'))
        cobranca = self.esperar_pagamento(cobranca)
        self.assertEqual(cobranca.status, Cobranca.Status.PAGA)
        self.recarregar()
        self.assertTrue(self.parcelas[0].pago)

    def test_3_checkout_de_cartao_devolve_o_link_de_pagamento(self):
        cobranca = gerar_cobranca(self.parcelas[0], Cobranca.Forma.CARTAO, Cobranca.Origem.CLIENTE)
        self.assertTrue(cobranca.pagbank_id.startswith('CHEC_'))
        self.assertTrue(cobranca.link_pagamento.startswith('https://'))
        self.assertEqual(cobranca.valor_total, Decimal('31.58'))
        print(f'\n[sandbox] link do checkout para pagar com cartão de teste: {cobranca.link_pagamento}')

    def test_4_pix_de_varias_parcelas_baixa_todas(self):
        ids = [self.parcelas[0].pk, self.parcelas[1].pk]
        cobranca = gerar_cobranca_de_parcelas(self.pagamento, ids, Cobranca.Forma.PIX, Cobranca.Origem.BOT)
        self.assertEqual(cobranca.valor_total, Decimal('60.00'))
        cobranca = self.esperar_pagamento(cobranca)
        self.recarregar()
        self.assertEqual(cobranca.acerto_manual, '')
        self.assertTrue(self.parcelas[0].pago and self.parcelas[1].pago)
        self.assertFalse(self.parcelas[2].pago)

    def test_5_pix_da_quitacao_aplica_desconto_e_quita(self):
        cobranca = gerar_quitacao(self.pagamento, Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        self.assertEqual(cobranca.valor_total, Decimal('81.00'))
        cobranca = self.esperar_pagamento(cobranca)
        self.recarregar()
        self.assertEqual(cobranca.acerto_manual, '')
        self.assertTrue(self.pagamento.quitado)
        self.assertTrue(all(p.pago for p in self.parcelas))

    def test_6_pedir_de_novo_reaproveita_sem_chamar_o_pagbank(self):
        primeira = gerar_cobranca(self.parcelas[2], Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        chamadas = RegistroPagBank.objects.count()
        segunda = gerar_cobranca(self.parcelas[2], Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(RegistroPagBank.objects.count(), chamadas)
        self.assertGreater(primeira.expira_em, timezone.now())


URL_PUBLICA = os.environ.get('PAGBANK_SANDBOX_URL_PUBLICA', '')
ESPERA_AVISO = 120  # segundos


@unittest.skipUnless(LIGADO and URL_PUBLICA, 'Exige PAGBANK_SANDBOX_E2E=1 e PAGBANK_SANDBOX_URL_PUBLICA (túnel https).')
@override_settings(CRM_TAREFAS_SINCRONAS=True, NOTIFICACAO_WS_SINCRONO=False, CRM_CACHE_LIMITES='default',
                   ALLOWED_HOSTS=['*'])
class SandboxWebhookE2E(CenarioSandbox, LiveServerTestCase):
    """O PagBank manda o aviso de verdade (pelo túnel) ao servidor de teste, que dá baixa sozinho."""

    port = int(os.environ.get('PAGBANK_SANDBOX_PORTA', '8765'))

    def setUp(self):
        self.montar_cenario()
        self.cabecalhos_recebidos = []
        from pagamentos_online.webhook import NotificacaoPagBankView

        original = NotificacaoPagBankView.post
        recebidos = self.cabecalhos_recebidos

        def espiar(view, request):
            resposta = original(view, request)
            recebidos.append({'cabecalhos': sorted(k.lower() for k in request.headers.keys()),
                              'status': resposta.status_code})
            return resposta

        patch = mock.patch.object(NotificacaoPagBankView, 'post', espiar)
        patch.start()
        self.addCleanup(patch.stop)

    def _salvar_cabecalhos(self):
        destino = Path(os.environ.get('PAGBANK_SANDBOX_SAIDA') or tempfile.gettempdir())
        (destino / 'avisos_recebidos.json').write_text(json.dumps(self.cabecalhos_recebidos, indent=2))

    def test_aviso_real_do_pix_da_baixa_sem_consulta_manual(self):
        cobranca = gerar_cobranca(self.parcelas[0], Cobranca.Forma.PIX, Cobranca.Origem.CLIENTE)
        limite = time.monotonic() + ESPERA_AVISO
        while time.monotonic() < limite:
            if Cobranca.objects.filter(pk=cobranca.pk, status=Cobranca.Status.PAGA).exists():
                break
            time.sleep(2)
        self._salvar_cabecalhos()
        print(f'\n[sandbox] avisos recebidos: {self.cabecalhos_recebidos}')
        self.assertTrue(self.cabecalhos_recebidos, 'Nenhum aviso do PagBank chegou pelo túnel.')
        self.assertTrue(any(r['status'] == 200 for r in self.cabecalhos_recebidos),
                        'Os avisos chegaram, mas foram recusados (veja os cabeçalhos de assinatura).')
        cobranca.refresh_from_db()
        self.parcelas[0].refresh_from_db()
        self.assertEqual(cobranca.status, Cobranca.Status.PAGA)
        self.assertTrue(self.parcelas[0].pago)

    @unittest.skipUnless(os.environ.get('PAGBANK_SANDBOX_CARTAO') == '1', 'Exige PAGBANK_SANDBOX_CARTAO=1 (pagar à mão).')
    def test_cartao_pago_no_checkout_da_baixa_pelo_aviso(self):
        """Gera o checkout e espera alguém pagar no navegador com um cartão de teste (15 minutos)."""
        cobranca = gerar_cobranca(self.parcelas[0], Cobranca.Forma.CARTAO, Cobranca.Origem.CLIENTE)
        destino = Path(os.environ.get('PAGBANK_SANDBOX_SAIDA') or tempfile.gettempdir())
        (destino / 'link_checkout.txt').write_text(cobranca.link_pagamento)
        limite = time.monotonic() + 900
        while time.monotonic() < limite:
            if Cobranca.objects.filter(pk=cobranca.pk, status=Cobranca.Status.PAGA).exists():
                break
            time.sleep(3)
        self._salvar_cabecalhos()
        cobranca.refresh_from_db()
        self.parcelas[0].refresh_from_db()
        self.assertEqual(cobranca.status, Cobranca.Status.PAGA)
        self.assertTrue(cobranca.pagbank_pedido_id.startswith('ORDE_'))
        self.assertTrue(self.parcelas[0].pago)
