"""Comportamento de arquivos de mídia independente do backend (disco ou S3).

Cobre os pontos que mudam quando o storage passa a ser remoto: nomes únicos
ao mover arquivos de `vendas/temp/` e o signal de WebP não abrindo arquivos
já salvos (no S3 cada abertura é uma requisição de rede).
"""

import shutil
import tempfile
from datetime import date
from decimal import Decimal
from unittest import mock

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from vendas.models import Cliente, ComprovantesCliente, Loja, Venda

PNG_MINIMO = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

MEDIA_TEMPORARIA = tempfile.mkdtemp(prefix='media-storage-teste-')


@override_settings(MEDIA_ROOT=MEDIA_TEMPORARIA, STORAGES={
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'LOCATION': MEDIA_TEMPORARIA,
    },
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MediaStorageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_TEMPORARIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        # O banco volta a cada teste, os arquivos não: começa sempre com a mídia vazia.
        shutil.rmtree(MEDIA_TEMPORARIA, ignore_errors=True)
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.vendedor = User.objects.create_user(
            username='vendedor', email='vendedor@teste.com', password='x', loja=self.loja,
        )
        self.cliente = Cliente.objects.create(
            nome='Cliente Teste', telefone='91999999999', cpf='12345678900',
            nascimento=date(1990, 1, 1), rg='123', cep='66000000',
            endereco='Rua A', bairro='Centro', cidade='Belém',
            comprovantes=ComprovantesCliente.objects.create(),
        )

    def _proximo_pk_venda(self):
        ultima = Venda.objects.order_by('-pk').first()
        return (ultima.pk if ultima else 0) + 1

    def test_venda_move_documento_de_temp_para_pasta_da_venda(self):
        venda = Venda.objects.create(
            cliente=self.cliente, vendedor=self.vendedor, loja=self.loja,
            repasse_logista=Decimal('100.00'),
            documento_assinado=SimpleUploadedFile('contrato.pdf', b'%PDF-NOVO'),
        )

        venda.refresh_from_db()
        self.assertTrue(venda.documento_assinado.name.startswith(f'vendas/{venda.pk}/'))
        self.assertEqual(venda.documento_assinado.read(), b'%PDF-NOVO')
        self.assertFalse(default_storage.exists('vendas/temp/contrato.pdf'))

    def test_venda_nao_aponta_para_arquivo_de_outro_quando_nome_ja_existe(self):
        pk_previsto = self._proximo_pk_venda()
        default_storage.save(f'vendas/{pk_previsto}/contrato.pdf', ContentFile(b'%PDF-ANTIGO'))

        venda = Venda.objects.create(
            cliente=self.cliente, vendedor=self.vendedor, loja=self.loja,
            repasse_logista=Decimal('100.00'),
            documento_assinado=SimpleUploadedFile('contrato.pdf', b'%PDF-NOVO'),
        )

        self.assertEqual(venda.pk, pk_previsto)
        venda.refresh_from_db()
        self.assertEqual(venda.documento_assinado.read(), b'%PDF-NOVO')
        with default_storage.open(f'vendas/{pk_previsto}/contrato.pdf') as antigo:
            self.assertEqual(antigo.read(), b'%PDF-ANTIGO')

    def test_signal_webp_converte_upload_novo(self):
        loja = Loja.objects.create(
            nome='Loja Logo', logo_loja=SimpleUploadedFile('logo.png', PNG_MINIMO, content_type='image/png'),
        )

        self.assertTrue(loja.logo_loja.name.endswith('.webp'))

    def test_signal_webp_nao_abre_arquivo_ja_salvo(self):
        loja = Loja.objects.create(
            nome='Loja Logo', logo_loja=SimpleUploadedFile('logo.png', PNG_MINIMO, content_type='image/png'),
        )
        loja = Loja.objects.get(pk=loja.pk)

        with mock.patch.object(
            FileSystemStorage, 'open', autospec=True, side_effect=FileSystemStorage.open,
        ) as abrir:
            loja.nome = 'Loja Renomeada'
            loja.save()

        abrir.assert_not_called()
