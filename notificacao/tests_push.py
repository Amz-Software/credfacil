"""Web Push: inscrição pela API, envio criptografado com VAPID e limpeza de aparelho expirado."""
import base64
import io
import os
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from notificacao import push
from notificacao.models import AssinaturaPush

ENDPOINT = 'https://fcm.googleapis.com/fcm/send/abc123'


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b'=').decode()


def chaves_vapid() -> dict:
    saida = io.StringIO()
    call_command('gerar_chaves_vapid', stdout=saida)
    pares = dict(linha.split('=', 1) for linha in saida.getvalue().splitlines() if linha.startswith('VAPID_'))
    return {'VAPID_PUBLIC_KEY': pares['VAPID_PUBLIC_KEY'], 'VAPID_PRIVATE_KEY': pares['VAPID_PRIVATE_KEY']}


def chaves_do_navegador() -> dict:
    """Chaves que o navegador gera ao assinar (p256dh = ponto público, auth = 16 bytes)."""
    publica = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
    )
    return {'p256dh': _b64url(publica), 'auth': _b64url(os.urandom(16))}


class RespostaFalsa:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ''
        self.headers = {}
        self.reason = ''


VAPID = chaves_vapid()


@override_settings(**VAPID, NOTIFICACAO_WS_SINCRONO=True)
class InscricaoApiTests(APITestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='vend', email='v@t.com', password='x')
        self.client.force_authenticate(self.usuario)

    def test_chave_publica_e_inscricao_idempotente(self):
        chave = self.client.get(reverse('api-push-chave')).json()
        corpo = {'endpoint': ENDPOINT, 'keys': chaves_do_navegador()}

        self.assertEqual(chave, {'ativo': True, 'chave_publica': VAPID['VAPID_PUBLIC_KEY']})
        self.assertEqual(self.client.post(reverse('api-push-assinaturas'), corpo, format='json').status_code, 201)
        self.assertEqual(self.client.post(reverse('api-push-assinaturas'), corpo, format='json').status_code, 201)
        self.assertEqual(AssinaturaPush.objects.filter(usuario=self.usuario).count(), 1)

        self.assertEqual(self.client.delete(reverse('api-push-assinaturas'), {'endpoint': ENDPOINT}, format='json').status_code, 204)
        self.assertFalse(AssinaturaPush.objects.exists())

    def test_recusa_endpoint_sem_https_e_sem_chaves_no_servidor(self):
        corpo = {'endpoint': 'http://inseguro.com/x', 'keys': chaves_do_navegador()}
        self.assertEqual(self.client.post(reverse('api-push-assinaturas'), corpo, format='json').status_code, 400)
        with override_settings(VAPID_PRIVATE_KEY=''):
            self.assertEqual(self.client.get(reverse('api-push-chave')).json()['ativo'], False)

    def test_exige_login(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(reverse('api-push-chave')).status_code, (401, 403))


@override_settings(**VAPID, NOTIFICACAO_WS_SINCRONO=True)
class EnvioPushTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username='vend', email='v@t.com', password='x')
        self.assinatura = AssinaturaPush.objects.create(usuario=self.usuario, endpoint=ENDPOINT, **chaves_do_navegador())

    def _agendar(self, event='proposta_aceita'):
        with self.captureOnCommitCallbacks(execute=True):
            push.agendar(self.usuario.id, event, 'Proposta da Maria aprovada.', '', '/app/solicitacoes/7')

    def test_envia_criptografado_com_vapid_para_o_endpoint(self):
        with mock.patch('pywebpush.requests.post', return_value=RespostaFalsa(201)) as post:
            self._agendar()

        self.assertEqual(post.call_count, 1)
        url = post.call_args.args[0]
        cabecalhos = post.call_args.kwargs['headers']
        self.assertEqual(url, ENDPOINT)
        self.assertIn('vapid', cabecalhos['Authorization'].lower())
        self.assertEqual(cabecalhos['Content-Encoding'], 'aes128gcm')
        self.assertNotIn(b'Maria', post.call_args.kwargs['data'])  # corpo cifrado

    def test_evento_sem_acao_do_vendedor_nao_vira_push(self):
        with mock.patch('pywebpush.requests.post') as post:
            self._agendar(event='proposta_criada')
        post.assert_not_called()

    def test_aparelho_expirado_e_removido(self):
        with mock.patch('pywebpush.requests.post', return_value=RespostaFalsa(410)):
            self._agendar()
        self.assertFalse(AssinaturaPush.objects.exists())

    def test_falha_de_rede_nao_levanta(self):
        with mock.patch('pywebpush.requests.post', side_effect=OSError('sem rede')):
            self._agendar()
        self.assertTrue(AssinaturaPush.objects.exists())
