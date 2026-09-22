import shutil
import tempfile
from datetime import datetime
from io import BytesIO

from PIL import Image

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from vendas.models import Cliente, ComprovantesCliente, Loja, PreAnaliseRapida
from vendas.views import PreAnaliseRapidaDetailView, PreAnaliseRapidaListView


def _arquivo(nome='serasa.pdf'):
    return SimpleUploadedFile(nome, b'%PDF-1.4 conteudo', content_type='application/pdf')


def _imagem(nome='rg.png'):
    buffer = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type='image/png')


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


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix='credfacil-test-media-'))
class SegundaCompraNaAnaliseRapidaTests(TestCase):
    """Campo 'É a segunda compra do cliente conosco?' no fluxo da pré-análise."""

    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.vendedor = User.objects.create_user(
            username='vendedor2', email='vendedor2@teste.com', password='x', loja=self.loja,
        )
        self.vendedor.user_permissions.add(
            Permission.objects.get(codename='add_cliente'),
            Permission.objects.get(codename='view_cliente'),
        )
        self.vendedor.lojas.add(self.loja)

    def _payload(self, segunda_compra):
        return {
            'nome_completo': 'Cliente Segunda Compra',
            'cpf': '123.456.789-00',
            'foto_rg_frente': _imagem('frente.png'),
            'foto_rg_verso': _imagem('verso.png'),
            'tem_comprovante_residencia': 'true',
            'possui_duas_referencias': 'true',
            'segunda_compra': segunda_compra,
        }

    def test_vendedor_marca_segunda_compra(self):
        self.client.force_login(self.vendedor)
        response = self.client.post('/api/pre-analises-rapidas/', self._payload('true'))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(PreAnaliseRapida.objects.get(pk=response.json()['id']).segunda_compra)

    def test_vendedor_marca_primeira_compra(self):
        self.client.force_login(self.vendedor)
        response = self.client.post('/api/pre-analises-rapidas/', self._payload('false'))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(PreAnaliseRapida.objects.get(pk=response.json()['id']).segunda_compra)

    def test_segunda_compra_exposta_na_leitura(self):
        pre = PreAnaliseRapida.objects.create(
            nome_completo='Cliente Teste', cpf='12345678900',
            loja=self.loja, criado_por=self.vendedor, segunda_compra=True,
        )
        self.client.force_login(self.vendedor)
        response = self.client.get(f'/api/pre-analises-rapidas/{pre.pk}/')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()['segunda_compra'])


class FiltrosListaAnaliseRapidaTests(TestCase):
    """Filtros de loja e data na listagem de análises rápidas (front Django)."""

    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja A')
        self.loja_b = Loja.objects.create(nome='Loja B')
        self.analista = User.objects.create_user(
            username='analista-filtros', email='analista-filtros@teste.com',
            password='x', loja=self.loja_a,
        )
        self.analista.user_permissions.add(
            Permission.objects.get(codename='view_cliente'),
            Permission.objects.get(codename='view_all_analise_credito'),
        )

        self.pre_a = self._criar('Cliente Loja A', self.loja_a, '2026-09-01 10:00')
        self.pre_b = self._criar('Cliente Loja B', self.loja_b, '2026-09-10 10:00')

    def _criar(self, nome, loja, criado_em):
        pre = PreAnaliseRapida.objects.create(
            nome_completo=nome, cpf='12345678900', loja=loja, criado_por=self.analista,
        )
        # criado_em é auto_now_add: precisa ser reescrito direto no banco
        momento = timezone.make_aware(datetime.strptime(criado_em, '%Y-%m-%d %H:%M'))
        PreAnaliseRapida.objects.filter(pk=pre.pk).update(criado_em=momento)
        return pre

    def _contexto(self, user=None, **params):
        # RequestFactory: mesma razão do detalhe — evita o render do test client.
        request = RequestFactory().get(reverse('vendas:pre_analise_rapida_list'), params)
        request.user = user or self.analista
        response = PreAnaliseRapidaListView.as_view()(request)
        return response.context_data

    def _listar(self, **params):
        return list(self._contexto(**params)['pre_analises'])

    def test_sem_filtro_lista_todas(self):
        self.assertCountEqual(self._listar(), [self.pre_a, self.pre_b])

    def test_filtra_por_loja(self):
        self.assertEqual(self._listar(loja=self.loja_b.pk), [self.pre_b])

    def test_filtra_por_data_inicio(self):
        self.assertEqual(self._listar(data_inicio='2026-09-05'), [self.pre_b])

    def test_filtra_por_data_fim_inclui_o_dia_inteiro(self):
        self.assertEqual(self._listar(data_fim='2026-09-10'), [self.pre_b, self.pre_a])

    def test_filtra_por_intervalo_de_datas(self):
        self.assertEqual(
            self._listar(data_inicio='2026-09-01', data_fim='2026-09-01'), [self.pre_a]
        )

    def test_combina_loja_e_data(self):
        self.assertEqual(self._listar(loja=self.loja_a.pk, data_inicio='2026-09-05'), [])

    def test_valores_invalidos_sao_ignorados(self):
        self.assertCountEqual(self._listar(loja='abc', data_inicio='ontem'), [self.pre_a, self.pre_b])

    def test_select_de_lojas_respeita_escopo_do_usuario(self):
        vendedor = User.objects.create_user(
            username='vendedor-filtros', email='vendedor-filtros@teste.com',
            password='x', loja=self.loja_a,
        )
        vendedor.user_permissions.add(Permission.objects.get(codename='view_cliente'))
        vendedor.lojas.add(self.loja_a)

        ctx = self._contexto(user=vendedor)
        self.assertEqual(list(ctx['lojas']), [self.loja_a])
        self.assertEqual(list(ctx['pre_analises']), [self.pre_a])
