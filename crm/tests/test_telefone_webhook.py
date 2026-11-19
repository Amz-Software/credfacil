import hashlib
import hmac
import json
import os
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from crm.models import Conversa, Mensagem
from crm.telefone import chave_telefone, formatar_telefone, mesmo_telefone
from crm.tests.base import CrmTestCase
from crm.webhook import normalizar

SEGREDO = 'segredo-de-teste'


class TelefoneTests(SimpleTestCase):
    def test_wa_id_sem_nono_digito_casa_com_cadastro(self):
        self.assertTrue(mesmo_telefone('559199990000', '(91) 99999-0000'))
        self.assertTrue(mesmo_telefone('5591999990000', '91999990000'))

    def test_numeros_diferentes_nao_casam(self):
        self.assertFalse(mesmo_telefone('5591999990000', '5591999990001'))

    def test_chave_e_formatacao(self):
        self.assertEqual(chave_telefone('+55 (91) 99999-0000'), '559199990000')
        self.assertEqual(formatar_telefone('5591999990000'), '+55 (91) 99999-0000')


def _payload(mensagens=None, statuses=None, nome='Maria Souza', telefone='5591999990000'):
    return {'object': 'whatsapp_business_account', 'entry': [{'changes': [{'field': 'messages', 'value': {
        'contacts': [{'wa_id': telefone, 'profile': {'name': nome}}],
        'messages': mensagens or [], 'statuses': statuses or [],
    }}]}]}


class WebhookTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        self.env_meta = mock.patch.dict(os.environ, {'WHATSAPP_APP_SECRET': SEGREDO, 'WHATSAPP_VERIFY_TOKEN': 'verifica'})
        self.env_meta.start()
        self.addCleanup(self.env_meta.stop)
        self.url = reverse('whatsapp-webhook')

    def _post(self, payload, assinar=True):
        corpo = json.dumps(payload).encode()
        cabecalho = 'sha256=' + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest() if assinar else ''
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, corpo, content_type='application/json',
                                    HTTP_X_HUB_SIGNATURE_256=cabecalho)

    def test_handshake_devolve_challenge_com_token_certo(self):
        ok = self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'verifica', 'hub.challenge': '42'})
        errado = self.client.get(self.url, {'hub.mode': 'subscribe', 'hub.verify_token': 'x', 'hub.challenge': '42'})

        self.assertEqual((ok.status_code, ok.content), (200, b'42'))
        self.assertEqual(errado.status_code, 403)

    def test_post_sem_assinatura_e_recusado(self):
        resposta = self._post(_payload([{'id': 'wamid.1', 'from': '5591999990000', 'type': 'text',
                                         'text': {'body': 'oi'}}]), assinar=False)

        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Mensagem.objects.exists())

    def test_post_sem_app_secret_configurado_e_recusado(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_APP_SECRET': ''}):
            resposta = self._post(_payload([{'id': 'wamid.1', 'from': '5591999990000', 'type': 'text',
                                             'text': {'body': 'oi'}}]))

        self.assertEqual(resposta.status_code, 403)

    def test_mensagem_valida_cria_conversa_e_reentrega_nao_duplica(self):
        mensagem = {'id': 'wamid.1', 'from': '5591999990000', 'timestamp': '1700000000', 'type': 'text',
                    'text': {'body': 'Quero comprar um celular'}}

        primeira = self._post(_payload([mensagem]))
        segunda = self._post(_payload([mensagem]))

        self.assertEqual((primeira.status_code, segunda.status_code), (200, 200))
        conversa = Conversa.objects.get()
        self.assertEqual(conversa.contato_nome, 'Maria Souza')
        self.assertEqual(Mensagem.objects.filter(direcao=Mensagem.Direcao.ENTRADA).count(), 1)

    def test_payload_quebrado_responde_200(self):
        corpo = b'{nao e json'
        cabecalho = 'sha256=' + hmac.new(SEGREDO.encode(), corpo, hashlib.sha256).hexdigest()

        resposta = self.client.post(self.url, corpo, content_type='application/json', HTTP_X_HUB_SIGNATURE_256=cabecalho)

        self.assertEqual(resposta.status_code, 200)

    def test_status_so_avanca_e_erro_e_terminal(self):
        conversa = self.conversa_com_humano()
        self.api(self.atendente).post(f'/api/crm/conversas/{conversa.pk}/enviar/', {'texto': 'Olá!'}, format='json')
        saida = Mensagem.objects.get(direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.HUMANO)

        for status in ('read', 'delivered'):
            self._post(_payload(statuses=[{'id': saida.wa_message_id, 'status': status}]))
        saida.refresh_from_db()
        lido = saida.status
        self._post(_payload(statuses=[{'id': saida.wa_message_id, 'status': 'failed',
                                       'errors': [{'code': 131026, 'title': 'x'}]}]))
        saida.refresh_from_db()

        self.assertEqual(lido, Mensagem.Status.LIDO)
        self.assertEqual(saida.status, Mensagem.Status.ERRO)
        self.assertIn('código 131026', saida.erro)


class NormalizacaoTests(SimpleTestCase):
    def test_tipos_principais(self):
        nomes = {'5591999990000': 'Maria'}
        base = {'from': '5591999990000', 'id': 'w1'}
        audio = normalizar({**base, 'type': 'audio', 'audio': {'id': 'm1', 'mime_type': 'audio/ogg', 'voice': True}}, nomes)
        local = normalizar({**base, 'type': 'location', 'location': {'latitude': -1.4, 'longitude': -48.5}}, nomes)
        reacao = normalizar({**base, 'type': 'reaction', 'reaction': {'emoji': '👍', 'message_id': 'w0'}}, nomes)
        botao = normalizar({**base, 'type': 'button', 'button': {'text': 'SIM', 'payload': 'ok'}}, nomes)

        self.assertEqual((audio.tipo, audio.midia_id, audio.midia_meta['voz']), ('AUDIO', 'm1', True))
        self.assertEqual(local.dados['localizacao']['latitude'], -1.4)
        self.assertEqual(reacao.dados['reacao'], {'emoji': '👍', 'alvo_wa_id': 'w0'})
        self.assertEqual((botao.tipo, botao.texto), ('TEXTO', 'SIM'))
        self.assertEqual(audio.contato_nome, 'Maria')
