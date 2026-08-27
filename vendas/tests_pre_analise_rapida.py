import shutil
import tempfile

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from vendas.models import Cliente, ComprovantesCliente, Loja, PreAnaliseRapida
from vendas.views import PreAnaliseRapidaDetailView


def _arquivo(nome='serasa.pdf'):
    return SimpleUploadedFile(nome, b'%PDF-1.4 conteudo', content_type='application/pdf')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='credfacil-test-media-'))
class ConsultaSerasaNaAnaliseRapidaTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.analista = User.objects.create_user(
            username='analista', email='analista@teste.com', password='x', loja=self.loja,
        )
        self.analista.user_permissions.add(
            Permission.objects.get(codename='view_cliente'),
            Permission.objects.get(codename='change_status_analise'),
            Permission.objects.get(codename='view_all_analise_credito'),
        )
        self.vendedor = User.objects.create_user(
            username='vendedor', email='vendedor@teste.com', password='x', loja=self.loja,
        )
        self.vendedor.user_permissions.add(Permission.objects.get(codename='view_cliente'))

        self.pre = PreAnaliseRapida.objects.create(
            nome_completo='Cliente Teste', cpf='12345678900',
            loja=self.loja, criado_por=self.vendedor,
        )

    def _url_anexar(self):
        return reverse('vendas:pre_analise_rapida_consulta_serasa', args=[self.pre.pk])

    def test_analista_anexa_consulta_serasa(self):
        self.client.force_login(self.analista)
        resp = self.client.post(self._url_anexar(), {'consulta_serasa': _arquivo()})
        self.assertEqual(resp.status_code, 302)

        self.pre.refresh_from_db()
        self.assertTrue(self.pre.consulta_serasa)
        self.assertEqual(self.pre.consulta_serasa_anexada_por, self.analista)
        self.assertIsNotNone(self.pre.consulta_serasa_anexada_em)

    def test_vendedor_nao_pode_anexar(self):
        self.client.force_login(self.vendedor)
        resp = self.client.post(self._url_anexar(), {'consulta_serasa': _arquivo()})
        self.assertEqual(resp.status_code, 403)
        self.pre.refresh_from_db()
        self.assertFalse(self.pre.consulta_serasa)

    def _contexto_detalhe(self, user):
        # RequestFactory: a TemplateResponse não é renderizada, então o teste não
        # depende do render (que quebra no instrumento do test client neste ambiente).
        request = RequestFactory().get(self.pre.get_absolute_url())
        request.user = user
        response = PreAnaliseRapidaDetailView.as_view()(request, pk=self.pre.pk)
        return response.context_data

    def test_detalhe_libera_card_apenas_para_quem_gerencia(self):
        ctx = self._contexto_detalhe(self.analista)
        self.assertTrue(ctx['pode_gerenciar_serasa'])
        self.assertIn('form_consulta_serasa', ctx)

        ctx = self._contexto_detalhe(self.vendedor)
        self.assertFalse(ctx['pode_gerenciar_serasa'])

    def test_substituir_consulta_remove_arquivo_anterior(self):
        from django.core.files.storage import default_storage

        self.client.force_login(self.analista)
        self.client.post(self._url_anexar(), {'consulta_serasa': _arquivo('primeira.pdf')})
        self.pre.refresh_from_db()
        primeiro = self.pre.consulta_serasa.name

        self.client.post(self._url_anexar(), {'consulta_serasa': _arquivo('segunda.pdf')})
        self.pre.refresh_from_db()
        segundo = self.pre.consulta_serasa.name

        self.assertNotEqual(primeiro, segundo)
        self.assertFalse(default_storage.exists(primeiro))
        self.assertTrue(default_storage.exists(segundo))

    def test_remover_consulta(self):
        self.client.force_login(self.analista)
        self.client.post(self._url_anexar(), {'consulta_serasa': _arquivo()})
        resp = self.client.post(
            reverse('vendas:pre_analise_rapida_consulta_serasa_remover', args=[self.pre.pk])
        )
        self.assertEqual(resp.status_code, 302)
        self.pre.refresh_from_db()
        self.assertFalse(self.pre.consulta_serasa)

    def test_aplicar_consulta_serasa_preenche_comprovantes_do_cliente(self):
        self.pre.anexar_consulta_serasa(_arquivo(), user=self.analista)

        comprovantes = ComprovantesCliente.objects.create()
        cliente = Cliente.objects.create(
            nome='Cliente Teste', cpf='12345678900', nascimento='1990-01-01',
            comprovantes=comprovantes, loja=self.loja,
        )

        self.assertTrue(self.pre.aplicar_consulta_serasa(cliente, user=self.analista))
        comprovantes.refresh_from_db()
        self.assertTrue(comprovantes.consulta_serasa)
        self.assertIn('comprovantes_clientes/', comprovantes.consulta_serasa.name)

        # não sobrescreve um arquivo já existente
        self.assertFalse(self.pre.aplicar_consulta_serasa(cliente, user=self.analista))

    def test_sem_consulta_anexada_nao_altera_comprovantes(self):
        comprovantes = ComprovantesCliente.objects.create()
        cliente = Cliente.objects.create(
            nome='Sem Serasa', cpf='99988877766', nascimento='1990-01-01',
            comprovantes=comprovantes, loja=self.loja,
        )
        self.assertFalse(self.pre.aplicar_consulta_serasa(cliente, user=self.analista))
        comprovantes.refresh_from_db()
        self.assertFalse(comprovantes.consulta_serasa)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='credfacil-test-media-api-'))
class MarcarFinalizadaCopiaSerasaTests(TestCase):
    """Ao vincular o cliente gerado, a consulta Serasa da análise rápida deve
    aparecer já preenchida nos comprovantes da proposta."""

    @classmethod
    def tearDownClass(cls):
        from django.conf import settings
        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja API')
        self.vendedor = User.objects.create_user(
            username='vendedor-api', email='vendedor-api@teste.com', password='x', loja=self.loja,
        )
        self.vendedor.lojas.add(self.loja)
        self.vendedor.user_permissions.add(
            Permission.objects.get(codename='view_cliente'),
            Permission.objects.get(codename='add_venda'),
        )
        self.pre = PreAnaliseRapida.objects.create(
            nome_completo='Cliente API', cpf='12345678900', status='A',
            loja=self.loja, criado_por=self.vendedor,
        )
        self.pre.anexar_consulta_serasa(_arquivo(), user=self.vendedor)

        self.comprovantes = ComprovantesCliente.objects.create()
        self.cliente = Cliente.objects.create(
            nome='Cliente API', cpf='12345678900', nascimento='1990-01-01',
            comprovantes=self.comprovantes, loja=self.loja,
        )

    def test_marcar_finalizada_copia_consulta_para_comprovantes(self):
        self.client.force_login(self.vendedor)
        resp = self.client.post(
            f'/api/pre-analises-rapidas/{self.pre.pk}/marcar-finalizada/',
            {'cliente': self.cliente.pk},
        )
        self.assertEqual(resp.status_code, 200, resp.content)

        self.pre.refresh_from_db()
        self.comprovantes.refresh_from_db()
        self.assertEqual(self.pre.cliente_gerado_id, self.cliente.pk)
        self.assertTrue(self.comprovantes.consulta_serasa)

    def test_serializer_expoe_apenas_indicador_do_serasa(self):
        self.client.force_login(self.vendedor)
        resp = self.client.get(f'/api/pre-analises-rapidas/{self.pre.pk}/')
        self.assertEqual(resp.status_code, 200, resp.content)
        dados = resp.json()
        self.assertTrue(dados['tem_consulta_serasa'])
        self.assertNotIn('consulta_serasa', dados)
