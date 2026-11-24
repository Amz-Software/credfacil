import uuid
from datetime import timedelta

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from vendas.models import ComprovanteParcela, Loja

from pagamentos_online.models import Cobranca

from .base import PagamentoOnlineTestCase, resposta_pix

BASE = '/api/publico/v1/'


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
    return buffer.getvalue()


class ApiPublicaTest(PagamentoOnlineTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.token = str(self.pagamento.token_publico)

    def url(self, caminho: str = '') -> str:
        return f'{BASE}pagamentos/{self.token}/{caminho}'

    def test_consulta_por_cpf_formatado_e_nascimento(self):
        resposta = self.client.post(f'{BASE}consulta/', {'cpf': '123.456.789-01', 'data_nascimento': '01/01/1990'},
                                    content_type='application/json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([p['token'] for p in resposta.json()['pagamentos']], [self.token])

    def test_consulta_com_nascimento_errado_nao_mostra_nada(self):
        resposta = self.client.post(f'{BASE}consulta/', {'cpf': '12345678901', 'data_nascimento': '1991-01-01'},
                                    content_type='application/json')
        self.assertEqual(resposta.json()['pagamentos'], [])

    def test_detalhe_mostra_parcelas_e_nao_expoe_cpf(self):
        resposta = self.client.get(self.url())
        dados = resposta.json()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(dados['parcelas']), 3)
        self.assertEqual(dados['cliente'], {'primeiro_nome': 'Maria'})
        self.assertTrue(dados['pagamento_online'])
        self.assertEqual(dados['parcelas'][0]['situacao'], 'atrasada')
        self.assertTrue(dados['parcelas'][0]['pode_pagar_online'])
        self.assertNotIn('12345678901', resposta.content.decode())

    def test_sem_pagamento_online_mostra_pix_da_chave_da_empresa(self):
        Loja.objects.create(nome='CredFacil', credfacil=True, chave_pix='12345678000199')
        self.configuracao.ativo = False
        self.configuracao.save()
        parcela = self.client.get(self.url()).json()['parcelas'][0]
        self.assertFalse(parcela['pode_pagar_online'])
        self.assertTrue(parcela['pix_estatico']['copia_cola'].startswith('000201'))
        self.assertTrue(parcela['pix_estatico']['qr_code_base64'])

    def test_token_inexistente_responde_404_no_contrato(self):
        resposta = self.client.get(f'{BASE}pagamentos/{uuid.uuid4()}/')
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.json()['erro']['codigo'], 'nao_encontrado')

    def test_opcoes_e_criacao_do_pix(self):
        opcoes = self.client.get(self.url(f'parcelas/{self.parcela.pk}/opcoes/')).json()['opcoes']
        self.assertEqual([o['forma'] for o in opcoes], ['pix', 'boleto', 'cartao'])
        with self.pagbank((201, lambda corpo: resposta_pix(corpo['reference_id']))):
            resposta = self.client.post(self.url(f'parcelas/{self.parcela.pk}/cobrancas/'), {'forma': 'pix'},
                                        content_type='application/json')
        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        self.assertTrue(dados['pix_copia_cola'])
        self.assertTrue(dados['qr_code_base64'])
        situacao = self.client.get(self.url(f'cobrancas/{dados["referencia"]}/')).json()
        self.assertEqual(situacao['status'], 'pendente')

    def test_parcela_de_outro_pagamento_nao_e_acessivel(self):
        from backoffice_api.financeiro.tests.fabricas import criar_conta

        outro = criar_conta(self.loja, cpf='99999999999')
        parcela_alheia = outro.parcelas_pagamento.first()
        resposta = self.client.get(self.url(f'parcelas/{parcela_alheia.pk}/opcoes/'))
        self.assertEqual(resposta.status_code, 404)

    def test_informar_pagamento_com_comprovante(self):
        arquivo = SimpleUploadedFile('comprovante.png', _png(), content_type='image/png')
        resposta = self.client.post(self.url(f'parcelas/{self.parcela.pk}/informar/'), {'comprovante': arquivo})
        self.assertEqual(resposta.status_code, 200)
        self.parcela.refresh_from_db()
        self.assertTrue(self.parcela.pagamento_efetuado)
        self.assertFalse(self.parcela.pago)
        self.assertEqual(ComprovanteParcela.objects.filter(parcela=self.parcela).count(), 1)

    def test_informar_recusa_arquivo_nao_permitido(self):
        arquivo = SimpleUploadedFile('script.exe', b'MZ', content_type='application/octet-stream')
        resposta = self.client.post(self.url(f'parcelas/{self.parcela.pk}/informar/'), {'comprovante': arquivo})
        self.assertEqual(resposta.status_code, 400)
        self.parcela.refresh_from_db()
        self.assertFalse(self.parcela.pagamento_efetuado)

    def test_informar_quitacao_coloca_todas_em_confirmacao(self):
        resposta = self.client.post(self.url('informar-quitacao/'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.pagamento.parcelas_pagamento.filter(pagamento_efetuado=True).count(), 3)

    def test_paginas_antigas_redirecionam_para_o_app_so_quando_ligado(self):
        antiga = f'/pagamento/{self.token}/'
        self.assertNotEqual(self.client.get(antiga).status_code, 302)
        self.configuracao.redirecionar_paginas_antigas = True
        self.configuracao.save()
        resposta = self.client.get(antiga)
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta['Location'], f'https://vendas.exemplo.com/pagamento/{self.token}')
        consulta = self.client.get('/consultar-pagamentos/')
        self.assertEqual(consulta['Location'], 'https://vendas.exemplo.com/consultar-pagamentos')

    def test_comprovante_em_pdf_so_de_cobranca_paga(self):
        cobranca = Cobranca.objects.create(
            parcela=self.parcela, forma=Cobranca.Forma.PIX, origem=Cobranca.Origem.CLIENTE,
            valor_parcela=self.parcela.valor, valor_total=self.parcela.valor, pagbank_id='ORDE_1',
            expira_em=timezone.now() + timedelta(hours=1),
        )
        url = self.url(f'cobrancas/{cobranca.referencia}/comprovante/')
        self.assertEqual(self.client.get(url).status_code, 404)
        Cobranca.objects.filter(pk=cobranca.pk).update(status=Cobranca.Status.PAGA, paga_em=timezone.now())
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))


class EndurecimentoPublicoTest(PagamentoOnlineTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.token = str(self.pagamento.token_publico)

    def url(self, caminho: str = '') -> str:
        return f'{BASE}pagamentos/{self.token}/{caminho}'

    def test_pdf_falso_e_recusado(self):
        arquivo = SimpleUploadedFile('comprovante.pdf', b'<html>nao sou pdf</html>', content_type='application/pdf')
        resposta = self.client.post(self.url(f'parcelas/{self.parcela.pk}/informar/'), {'comprovante': arquivo})
        self.assertEqual(resposta.status_code, 400)

    def test_limite_de_consultas_por_cpf(self):
        corpo = {'cpf': '12345678901', 'data_nascimento': '2000-01-01'}
        respostas = [self.client.post(f'{BASE}consulta/', corpo, content_type='application/json').status_code
                     for _ in range(11)]
        self.assertEqual(respostas[-1], 429)
        self.assertEqual(set(respostas[:-1]), {200})

    def test_compra_encerrada_nao_aceita_informe(self):
        self.pagamento.quitado = True
        self.pagamento.save(update_fields=['quitado'])
        resposta = self.client.post(self.url(f'parcelas/{self.parcela.pk}/informar/'))
        self.assertEqual(resposta.status_code, 400)
