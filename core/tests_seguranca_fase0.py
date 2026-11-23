"""Fase 0 de segurança: mídia assinada, limite de tentativas nas views Django,
WebSocket (origem e JWT) e mutações só por POST."""
import shutil
import tempfile
from unittest import mock
from urllib.parse import quote

from asgiref.sync import async_to_sync
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from core import midia
from core.seguranca import ip_do_cliente, origens_websocket
from notificacao.jwt_middleware import JwtAuthMiddleware

MEDIA_TESTE = tempfile.mkdtemp(prefix='midia-assinada-')
STORAGES_ASSINADO = {
    'default': {'BACKEND': 'core.midia.MidiaAssinadaStorage', 'LOCATION': MEDIA_TESTE},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(MEDIA_ROOT=MEDIA_TESTE, STORAGES=STORAGES_ASSINADO, MIDIA_X_ACCEL_PREFIXO='')
class MidiaAssinadaTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.storage = storages['default']
        self.nome = self.storage.save('comprovantes_clientes/rg frente.jpg', ContentFile(b'\xff\xd8\xffJPEG'))

    def test_url_do_storage_leva_assinatura_e_abre(self):
        url = self.storage.url(self.nome)

        resposta = self.client.get(url)

        self.assertIn('?assinatura=', url)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(b''.join(resposta.streaming_content), b'\xff\xd8\xffJPEG')
        self.assertEqual(resposta['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn('attachment', resposta.get('Content-Disposition', ''))

    def test_sem_assinatura_responde_404(self):
        self.assertEqual(self.client.get(f'/mediafiles/{self.nome}').status_code, 404)

    def test_assinatura_de_outro_arquivo_responde_404(self):
        outro = self.storage.save('comprovantes_clientes/outro.jpg', ContentFile(b'\xff\xd8\xff'))
        token = midia.assinar(outro)
        self.assertEqual(self.client.get(f'/mediafiles/{self.nome}?assinatura={token}').status_code, 404)

    def test_assinatura_expirada_responde_404(self):
        url = self.storage.url(self.nome)
        with override_settings(MIDIA_ASSINATURA_HORAS=0), mock.patch('time.time', return_value=10**10):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_caminho_com_ponto_ponto_responde_404(self):
        caminho = 'comprovantes_clientes/../../core/settings.py'
        token = midia.assinar(caminho)
        self.assertEqual(self.client.get(f'/mediafiles/{caminho}?assinatura={token}').status_code, 404)

    def test_tipo_que_nao_e_imagem_nem_pdf_vai_como_anexo(self):
        nome = self.storage.save('vendas/1/pagina.html', ContentFile(b'<script>alert(1)</script>'))
        resposta = self.client.get(self.storage.url(nome))
        self.assertTrue(resposta['Content-Disposition'].startswith('attachment'))

    def test_x_accel_redirect_delega_ao_nginx(self):
        with override_settings(MIDIA_X_ACCEL_PREFIXO='/_midia/'):
            resposta = self.client.get(self.storage.url(self.nome))
        self.assertEqual(resposta['X-Accel-Redirect'], '/_midia/' + quote(self.nome))
        self.assertEqual(resposta.content, b'')


class LimiteDeTentativasDjangoTests(TestCase):
    TAXAS = {'anon': '1000/min', 'user': '1000/min', 'login': '2/min', 'publico': '2/min'}

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        taxas = override_settings(REST_FRAMEWORK={'DEFAULT_THROTTLE_RATES': self.TAXAS})
        taxas.enable()
        self.addCleanup(taxas.disable)

    def test_buscar_lojas_responde_lista_vazia_para_inexistente_e_limita(self):
        primeira = self.client.get('/buscar-lojas/?username=ninguem')
        self.client.get('/buscar-lojas/?username=ninguem')
        terceira = self.client.get('/buscar-lojas/?username=ninguem')

        self.assertEqual((primeira.status_code, primeira.json()), (200, {'lojas': []}))
        self.assertEqual(terceira.status_code, 429)

    def test_consulta_de_pagamentos_limita_o_post(self):
        url = reverse('vendas:consulta_pagamentos')
        dados = {'cpf': '00000000000', 'date_of_birth': '1990-01-01'}
        self.client.post(url, dados)
        self.client.post(url, dados)

        bloqueada = self.client.post(url, dados, follow=True)

        self.assertContains(bloqueada, 'Muitas tentativas')
        self.assertEqual(self.client.get(url).status_code, 200)  # GET não conta

    def test_recuperacao_de_senha_limita_o_post(self):
        url = reverse('accounts:password_reset')
        for _ in range(2):
            self.client.post(url, {'email': 'x@t.com'})
        bloqueada = self.client.post(url, {'email': 'x@t.com'})
        self.assertRedirects(bloqueada, url, fetch_redirect_response=False)

    def test_ip_do_cliente_usa_o_salto_do_proxy_confiavel(self):
        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='1.1.1.1, 2.2.2.2', REMOTE_ADDR='10.0.0.1')
        with override_settings(AXES_IPWARE_PROXY_COUNT=1):
            self.assertEqual(ip_do_cliente(request), '2.2.2.2')


class _Interna:
    def __init__(self):
        self.usuario = None

    async def __call__(self, scope, receive, send):
        self.usuario = scope.get('user')


class JwtWebSocketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ws', email='ws@t.com', password='x')

    def _usuario_com(self, token):
        interna = _Interna()
        scope = {'type': 'websocket', 'query_string': f'token={token}'.encode(), 'user': AnonymousUser()}
        async_to_sync(JwtAuthMiddleware(interna))(scope, None, None)
        return interna.usuario

    def test_access_token_autentica(self):
        self.assertEqual(self._usuario_com(str(RefreshToken.for_user(self.user).access_token)), self.user)

    def test_refresh_token_e_recusado(self):
        self.assertIsInstance(self._usuario_com(str(RefreshToken.for_user(self.user))), AnonymousUser)

    def test_usuario_inativo_e_recusado(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertIsInstance(self._usuario_com(token), AnonymousUser)

    def test_token_adulterado_e_recusado(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        self.assertIsInstance(self._usuario_com(token[:-2] + 'xx'), AnonymousUser)


class OrigensWebSocketTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=['credfacil.exemplo.com'], CORS_ALLOWED_ORIGINS=['https://vendas.exemplo.com'])
    def test_aceita_hosts_e_origem_da_spa_do_vendedor(self):
        from channels.security.websocket import OriginValidator
        from urllib.parse import urlparse

        validador = OriginValidator(None, origens_websocket())

        self.assertTrue(validador.valid_origin(urlparse('https://credfacil.exemplo.com')))
        self.assertTrue(validador.valid_origin(urlparse('https://vendas.exemplo.com')))
        self.assertFalse(validador.valid_origin(urlparse('https://atacante.com')))
        self.assertFalse(validador.valid_origin(None))


class MutacoesSoPorPostTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username='adm', email='a@t.com', password='x'))

    def test_rotas_de_mutacao_recusam_get(self):
        urls = [
            reverse('vendas:aprovar_analise', args=[1]),
            reverse('vendas:pre_analise_rapida_aprovar', args=[1]),
            reverse('vendas:pre_analise_rapida_reprovar', args=[1]),
            reverse('notificacao_ler_todas'),
            reverse('vendas:toggle_status_pagamento', args=[1, 1]),
        ] + [
            reverse(f'vendas:toggle_{nome}_pagamento', args=[1])
            for nome in ('bloqueio', 'desativar', 'sem_contato', 'mais_prazo', 'devolucao', 'bo',
                         'atrasado', 'sem_conexao', 'roubo', 'lembrete')
        ]
        self.assertEqual(len(urls), 15)
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_ler_todas_nao_redireciona_para_fora(self):
        resposta = self.client.post(reverse('ler_todas') + '?next=https://atacante.com/')
        self.assertEqual(resposta['Location'], reverse('notificacao_list'))

    def test_ler_todas_por_post_continua_funcionando(self):
        self.assertEqual(self.client.post(reverse('notificacao_ler_todas')).status_code, 302)
