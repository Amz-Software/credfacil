"""Anexo, visualização e remoção de comprovantes de pagamento por parcela.

Segue a convenção de `tests_contas_a_receber_acesso`: as checagens de acesso
permitido usam RequestFactory porque o instrumentador de templates do test
client do Django é incompatível com o Python desta venv.
"""

import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from financeiro.forms import ComprovanteParcelaForm
from financeiro.views import (
    ComprovanteParcelaDeleteView, ComprovanteParcelaDownloadView,
    ComprovanteParcelaUploadView, ContasAReceberDetailView,
)
from vendas.models import (
    Cliente, ComprovanteParcela, ComprovantesCliente, Loja, Pagamento, Parcela,
    TipoPagamento, Venda,
)

PERMISSOES_BASE = ('view_pagamento', 'change_pagamento', 'can_view_all_payments')

PNG_MINIMO = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

MEDIA_TEMPORARIA = tempfile.mkdtemp(prefix='comprovantes-teste-')


def _criar_usuario(username, loja, grupo):
    user = User.objects.create_user(
        username=username, email=f'{username}@teste.com', password='x', loja=loja,
    )
    user.user_permissions.add(*Permission.objects.filter(codename__in=PERMISSOES_BASE))
    user.groups.add(Group.objects.get_or_create(name=grupo)[0])
    return user


def _arquivo(nome='comprovante.png', conteudo=PNG_MINIMO, content_type='image/png'):
    return SimpleUploadedFile(nome, conteudo, content_type=content_type)


@override_settings(MEDIA_ROOT=MEDIA_TEMPORARIA, STORAGES={
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'LOCATION': MEDIA_TEMPORARIA,
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ComprovanteParcelaTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TEMPORARIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.factory = RequestFactory()
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.vendedor = _criar_usuario('vendedor', self.loja, 'VENDEDOR')
        self.analista = _criar_usuario('analista', self.loja, 'ANALISTA')
        self.admin = _criar_usuario('admin', self.loja, 'ADMINISTRADOR')

        cliente = Cliente.objects.create(
            nome='Cliente Teste', telefone='91999999999', cpf='12345678900',
            nascimento=date(1990, 1, 1), rg='123', cep='66000000',
            endereco='Rua A', bairro='Centro', cidade='Belém',
            comprovantes=ComprovantesCliente.objects.create(),
        )
        venda = Venda.objects.create(
            cliente=cliente, vendedor=self.vendedor, loja=self.loja,
            repasse_logista=Decimal('100.00'),
        )
        tipo = TipoPagamento.objects.create(nome='IPX', parcelas=True, caixa=False)
        self.pagamento = Pagamento.objects.create(
            venda=venda, tipo_pagamento=tipo, valor=Decimal('1000.00'),
            parcelas=10, loja=self.loja, data_primeira_parcela=date.today(),
        )
        self.parcela = Parcela.objects.create(
            pagamento=self.pagamento, numero_parcela=1, valor=Decimal('100.00'),
            data_vencimento=date.today() - timedelta(days=30), pago=False,
            loja=self.loja,
        )
        outro_pagamento = Pagamento.objects.create(
            venda=venda, tipo_pagamento=tipo, valor=Decimal('50.00'),
            parcelas=1, loja=self.loja, data_primeira_parcela=date.today(),
        )
        self.parcela_de_outro_pagamento = Parcela.objects.create(
            pagamento=outro_pagamento, numero_parcela=1, valor=Decimal('50.00'),
            data_vencimento=date.today(), pago=False, loja=self.loja,
        )

    # --- helpers ---

    def _request(self, metodo, url, user, data=None):
        request = getattr(self.factory, metodo)(url, data or {})
        request.user = user
        request.session = SessionStore()
        request.session['loja_id'] = self.loja.id
        request._messages = FallbackStorage(request)
        return request

    def _url_upload(self, parcela=None):
        parcela = parcela or self.parcela
        return reverse(
            'financeiro:comprovante_parcela_upload',
            args=[parcela.pagamento_id, parcela.pk],
        )

    def _url_download(self, comprovante):
        return reverse(
            'financeiro:comprovante_parcela_download',
            args=[self.pagamento.pk, self.parcela.pk, comprovante.pk],
        )

    def _url_delete(self, comprovante):
        return reverse(
            'financeiro:comprovante_parcela_delete',
            args=[self.pagamento.pk, self.parcela.pk, comprovante.pk],
        )

    def _enviar(self, user, arquivo=None, observacao='', parcela=None):
        parcela = parcela or self.parcela
        url = self._url_upload(parcela)
        request = self._request(
            'post', url, user,
            {'arquivo': arquivo if arquivo is not None else _arquivo(), 'observacao': observacao},
        )
        return ComprovanteParcelaUploadView.as_view()(
            request, pk=parcela.pagamento_id, parcela_pk=parcela.pk,
        )

    def _criar_comprovante(self, user=None):
        self._enviar(user or self.analista)
        return ComprovanteParcela.objects.get(parcela=self.parcela)

    # --- upload ---

    def test_analista_anexa_comprovante(self):
        response = self._enviar(self.analista, observacao='PIX recebido')

        self.assertEqual(response.status_code, 302)
        comprovante = ComprovanteParcela.objects.get(parcela=self.parcela)
        self.assertEqual(comprovante.observacao, 'PIX recebido')
        self.assertEqual(comprovante.criado_por, self.analista)
        self.assertEqual(comprovante.loja, self.loja)
        self.assertTrue(comprovante.is_imagem)

    def test_admin_anexa_comprovante(self):
        self._enviar(self.admin)

        self.assertEqual(ComprovanteParcela.objects.filter(parcela=self.parcela).count(), 1)

    def test_parcela_aceita_multiplos_comprovantes(self):
        self._enviar(self.analista, _arquivo('primeiro.png'))
        self._enviar(self.analista, _arquivo('segundo.png'))

        self.assertEqual(ComprovanteParcela.objects.filter(parcela=self.parcela).count(), 2)

    def test_anexa_pdf_sem_conversao_para_imagem(self):
        pdf = _arquivo('recibo.pdf', b'%PDF-1.4\n%%EOF\n', 'application/pdf')

        self._enviar(self.analista, pdf)

        comprovante = ComprovanteParcela.objects.get(parcela=self.parcela)
        self.assertTrue(comprovante.is_pdf)
        self.assertFalse(comprovante.is_imagem)
        self.assertTrue(comprovante.nome_arquivo.endswith('.pdf'))

    def test_vendedor_nao_anexa_comprovante(self):
        self.client.force_login(self.vendedor)

        response = self.client.post(self._url_upload(), {'arquivo': _arquivo()})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ComprovanteParcela.objects.exists())

    def test_upload_rejeita_extensao_nao_permitida(self):
        arquivo = _arquivo('malicioso.exe', b'MZ', 'application/octet-stream')

        response = self._enviar(self.analista, arquivo)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComprovanteParcela.objects.exists())

    def test_upload_rejeita_arquivo_acima_do_limite(self):
        excedente = b'0' * (ComprovanteParcela.TAMANHO_MAXIMO_BYTES + 1)
        form = ComprovanteParcelaForm(
            {}, {'arquivo': _arquivo('grande.pdf', excedente, 'application/pdf')},
        )

        self.assertFalse(form.is_valid())
        self.assertIn('arquivo', form.errors)

    def test_upload_exige_que_parcela_pertenca_ao_pagamento_da_url(self):
        url = reverse(
            'financeiro:comprovante_parcela_upload',
            args=[self.pagamento.pk, self.parcela_de_outro_pagamento.pk],
        )
        request = self._request('post', url, self.analista, {'arquivo': _arquivo()})

        view = ComprovanteParcelaUploadView.as_view()

        with self.assertRaises(Exception):
            view(request, pk=self.pagamento.pk, parcela_pk=self.parcela_de_outro_pagamento.pk)
        self.assertFalse(ComprovanteParcela.objects.exists())

    # --- visualização ---

    def test_analista_visualiza_comprovante_anexado(self):
        comprovante = self._criar_comprovante()

        response = ComprovanteParcelaDownloadView.as_view()(
            self._request('get', self._url_download(comprovante), self.analista),
            pk=self.pagamento.pk, parcela_pk=self.parcela.pk, comprovante_pk=comprovante.pk,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('attachment', response.headers.get('Content-Disposition', ''))
        # O conteúdo servido é o arquivo salvo no storage (imagens passam pela
        # conversão para WEBP do signal `convert_images_to_webp`).
        with comprovante.arquivo.open('rb') as salvo:
            self.assertEqual(b''.join(response.streaming_content), salvo.read())

    def test_download_forcado_envia_anexo(self):
        comprovante = self._criar_comprovante()

        response = ComprovanteParcelaDownloadView.as_view()(
            self._request('get', f'{self._url_download(comprovante)}?download=1', self.analista),
            pk=self.pagamento.pk, parcela_pk=self.parcela.pk, comprovante_pk=comprovante.pk,
        )

        self.assertIn('attachment', response.headers.get('Content-Disposition', ''))

    def test_vendedor_nao_visualiza_comprovante(self):
        comprovante = self._criar_comprovante()
        self.client.force_login(self.vendedor)

        response = self.client.get(self._url_download(comprovante))

        self.assertEqual(response.status_code, 403)

    # --- escopo por loja e limpeza de arquivos ---

    def test_analista_de_outra_loja_nao_acessa_comprovante(self):
        comprovante = self._criar_comprovante()
        outra_loja = Loja.objects.create(nome='Outra Loja')
        intruso = _criar_usuario('intruso', outra_loja, 'ANALISTA')
        intruso.user_permissions.remove(
            Permission.objects.get(codename='can_view_all_payments')
        )
        intruso = User.objects.get(pk=intruso.pk)  # limpa o cache de permissões

        request = self._request('get', self._url_download(comprovante), intruso)
        request.session['loja_id'] = outra_loja.id

        with self.assertRaises(Http404):
            ComprovanteParcelaDownloadView.as_view()(
                request, pk=self.pagamento.pk, parcela_pk=self.parcela.pk,
                comprovante_pk=comprovante.pk,
            )

    def test_analista_de_outra_loja_nao_anexa_comprovante(self):
        outra_loja = Loja.objects.create(nome='Outra Loja')
        intruso = _criar_usuario('intruso', outra_loja, 'ANALISTA')
        intruso.user_permissions.remove(
            Permission.objects.get(codename='can_view_all_payments')
        )
        intruso = User.objects.get(pk=intruso.pk)

        request = self._request('post', self._url_upload(), intruso, {'arquivo': _arquivo()})
        request.session['loja_id'] = outra_loja.id

        with self.assertRaises(Http404):
            ComprovanteParcelaUploadView.as_view()(
                request, pk=self.pagamento.pk, parcela_pk=self.parcela.pk,
            )
        self.assertFalse(ComprovanteParcela.objects.exists())

    def test_exclusao_em_cascata_da_parcela_apaga_o_arquivo(self):
        comprovante = self._criar_comprovante()
        caminho = comprovante.arquivo.name
        storage = comprovante.arquivo.storage
        self.assertTrue(storage.exists(caminho))

        # Deleção em massa (o mesmo caminho usado por `criar_ou_atualizar_parcelas`)
        Parcela.objects.filter(pk=self.parcela.pk).delete()

        self.assertFalse(ComprovanteParcela.objects.exists())
        self.assertFalse(storage.exists(caminho))

    # --- exibição na tela de detalhes ---

    def _html_detalhe(self, user):
        url = reverse('financeiro:contas_a_receber_update', args=[self.pagamento.pk])
        response = ContasAReceberDetailView.as_view()(
            self._request('get', url, user), pk=self.pagamento.pk,
        )
        self.assertEqual(response.status_code, 200)
        return response.render().content.decode()

    def _modal_da_parcela(self, html, parcela=None):
        """Recorta o HTML do modal de comprovantes de uma parcela específica."""
        parcela = parcela or self.parcela
        marcador = '<div class="modal fade" id="comprovanteModal-'
        for bloco in html.split(marcador)[1:]:
            if bloco.startswith(f'{parcela.pk}"'):
                return bloco
        self.fail(f'Modal da parcela {parcela.pk} não foi renderizado.')

    def _botao_da_parcela(self, html, parcela=None):
        """Recorta o HTML do botão de comprovante da linha de uma parcela."""
        parcela = parcela or self.parcela
        alvo = f'data-bs-target="#comprovanteModal-{parcela.pk}"'
        for pedaco in html.split('<button')[1:]:
            fim = pedaco.find('</button>')
            botao = pedaco[:fim]
            if alvo in botao and 'cr-comprovante-btn' in botao:
                return botao
        self.fail(f'Botão de comprovante da parcela {parcela.pk} não foi renderizado.')

    def test_detalhe_mostra_botao_anexar_quando_nao_ha_comprovante(self):
        html = self._html_detalhe(self.analista)

        modal = self._modal_da_parcela(html)
        self.assertIn('Nenhum comprovante anexado a esta parcela.', modal)
        self.assertIn(self._url_upload(), modal)

    def test_detalhe_sinaliza_parcela_com_comprovante_anexado(self):
        comprovante = self._criar_comprovante()

        html = self._html_detalhe(self.analista)

        modal = self._modal_da_parcela(html)
        self.assertNotIn('Nenhum comprovante anexado a esta parcela.', modal)
        self.assertIn(self._url_download(comprovante), modal)
        self.assertIn(comprovante.nome_arquivo, modal)
        # Linha da parcela ganha o destaque visual de "tem comprovante"
        botao = self._botao_da_parcela(html)
        self.assertIn('btn-success', botao)
        self.assertIn('bi-paperclip', botao)
        self.assertNotIn('btn-outline-secondary', botao)

    # --- remoção ---

    def test_analista_remove_comprovante_e_apaga_arquivo(self):
        comprovante = self._criar_comprovante()
        caminho = comprovante.arquivo.path
        storage = comprovante.arquivo.storage

        response = ComprovanteParcelaDeleteView.as_view()(
            self._request('post', self._url_delete(comprovante), self.analista),
            pk=self.pagamento.pk, parcela_pk=self.parcela.pk, comprovante_pk=comprovante.pk,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ComprovanteParcela.objects.exists())
        self.assertFalse(storage.exists(caminho))

    def test_vendedor_nao_remove_comprovante(self):
        comprovante = self._criar_comprovante()
        self.client.force_login(self.vendedor)

        response = self.client.post(self._url_delete(comprovante))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(ComprovanteParcela.objects.filter(pk=comprovante.pk).exists())

