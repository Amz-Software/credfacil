"""Upload/download de documentos, PDFs (WeasyPrint) e conversão segura do contrato Editor.js."""
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from backoffice_api.models import RegistroAuditoria
from vendas.models import Loja

from ..editorjs import editorjs_para_html
from ..servicos_documentos import TAMANHO_MAXIMO_BYTES
from .fabricas import CenarioVendas, cliente_logado, criar_usuario, url_venda

PDF = b'%PDF-1.4\n%teste\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
)


class DocumentosTests(CenarioVendas, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._media = override_settings(MEDIA_ROOT=cls.media)
        cls._media.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        perms = ('vendas.change_venda', 'vendas.view_venda')
        self.cliente = cliente_logado(criar_usuario('docs', permissoes=perms, lojas=(self.loja_a,)))
        self.url = url_venda(self.venda, 'documentos/')

    def enviar(self, **arquivos):
        return self.cliente.post(self.url, arquivos, format='multipart')

    def test_upload_valido_e_download_auditado(self):
        resposta = self.enviar(documento_assinado=SimpleUploadedFile('contrato.pdf', PDF, 'application/pdf'))
        self.assertEqual(resposta.status_code, 200, resposta.content)
        documento = next(d for d in resposta.json()['documentos'] if d['campo'] == 'documento_assinado')
        self.assertTrue(documento['presente'])
        self.assertNotIn('mediafiles', documento['url'])
        self.assertTrue(RegistroAuditoria.objects.filter(acao='venda_documentos_enviados').exists())

        download = self.cliente.get(documento['url'])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download['Content-Type'], 'application/pdf')
        self.assertEqual(download['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(b''.join(download.streaming_content), PDF)
        self.assertTrue(RegistroAuditoria.objects.filter(acao='venda_documento_acessado').exists())

    def test_tipo_e_tamanho_sao_validados_pelo_conteudo(self):
        falso = SimpleUploadedFile('contrato.pdf', b'<html>nao sou pdf</html>', 'application/pdf')
        resposta = self.enviar(documento_assinado=falso)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('documento_assinado', resposta.json()['erro']['campos'])
        pdf_na_foto = SimpleUploadedFile('foto.png', PDF, 'image/png')
        self.assertIn('foto_cliente', self.enviar(foto_cliente=pdf_na_foto).json()['erro']['campos'])
        grande = SimpleUploadedFile('g.pdf', PDF + b'0' * TAMANHO_MAXIMO_BYTES, 'application/pdf')
        self.assertEqual(self.enviar(documento_assinado=grande).status_code, 400)
        self.assertEqual(self.enviar().status_code, 400)

    def test_imagem_do_imei_so_para_iphone(self):
        resposta = self.enviar(imagem_imei=SimpleUploadedFile('imei.png', PNG, 'image/png'))
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('imagem_imei', resposta.json()['erro']['campos'])

    def test_download_sem_arquivo_404_e_sem_permissao_403(self):
        self.assertEqual(self.cliente.get(url_venda(self.venda, 'arquivos/foto_cliente/')).status_code, 404)
        self.assertEqual(self.cliente.get(url_venda(self.venda, 'arquivos/senha/')).status_code, 404)
        leitor = cliente_logado(criar_usuario('semver', permissoes=('vendas.change_venda',), lojas=(self.loja_a,)))
        self.assertEqual(leitor.get(url_venda(self.venda, 'arquivos/documento_assinado/')).status_code, 403)
        self.assertEqual(leitor.post(self.url, {}, format='multipart').status_code, 400)

    def test_outra_loja_404(self):
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000012')
        resposta = self.cliente.post(url_venda(outra, 'documentos/'),
                                     {'documento_assinado': SimpleUploadedFile('c.pdf', PDF)}, format='multipart')
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.cliente.get(url_venda(outra, 'arquivos/documento_assinado/')).status_code, 404)


class PdfsTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_da_analise()
        self.loja_a.contrato = {'blocks': [
            {'type': 'header', 'data': {'level': 3, 'text': '4. Cláusulas'}},
            {'type': 'paragraph', 'data': {'text': 'Texto <b>importante</b><script>alert(1)</script>'}},
        ]}
        self.loja_a.save()
        Loja.objects.create(nome='CredFacil', credfacil=True, chave_pix='pix@credfacil.com.br', telefone='91988887777')
        self.cliente = cliente_logado(criar_usuario('pdf', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))

    def assert_pdf(self, resposta):
        self.assertEqual(resposta.status_code, 200, getattr(resposta, 'content', b'')[:300])
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))

    def test_nota_contrato_e_carne(self):
        self.assert_pdf(self.cliente.get(url_venda(self.venda, 'nota.pdf')))
        self.assert_pdf(self.cliente.get(url_venda(self.venda, 'contrato.pdf'), HTTP_ACCEPT='application/pdf'))
        self.assert_pdf(self.cliente.get(url_venda(self.venda, 'carne.pdf'), {'tipo': 'promissoria'}))
        documentos = set(RegistroAuditoria.objects.filter(acao='venda_pdf_gerado').values_list('dados__documento', flat=True))
        self.assertEqual(documentos, {'nota', 'contrato', 'carne'})

    def test_erros_do_carne(self):
        self.assertEqual(self.cliente.get(url_venda(self.venda, 'carne.pdf'), {'tipo': 'boleto'}).status_code, 400)
        Loja.objects.filter(credfacil=True).update(chave_pix='')
        resposta = self.cliente.get(url_venda(self.venda, 'carne.pdf'), HTTP_ACCEPT='application/pdf')
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta['Content-Type'], 'application/json')
        manual = self.criar_venda_manual(cpf='11122233344', imei='350000000000013')
        manual.pagamentos.update(tipo_pagamento=self.tipo_entrada)
        self.assertEqual(self.cliente.get(url_venda(manual, 'carne.pdf')).status_code, 422)

    def test_permissao_escopo_e_metodo(self):
        sem = cliente_logado(criar_usuario('sem', lojas=(self.loja_a,)))
        self.assertEqual(sem.get(url_venda(self.venda, 'nota.pdf')).status_code, 403)
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000014')
        self.assertEqual(self.cliente.get(url_venda(outra, 'nota.pdf')).status_code, 404)
        self.assertEqual(self.cliente.post(url_venda(self.venda, 'nota.pdf')).status_code, 405)


class EditorJsTests(TestCase):
    def test_converte_blocos_como_o_script_do_navegador(self):
        html = editorjs_para_html({'blocks': [
            {'type': 'header', 'data': {'level': 2, 'text': 'Título'}},
            {'type': 'paragraph', 'data': {'text': 'Um <i>texto</i>'}},
            {'type': 'list', 'data': {'style': 'ordered', 'items': ['a', {'content': 'b', 'items': [{'content': 'c'}]}]}},
            {'type': 'image', 'data': {'url': 'http://x'}},
        ]})
        self.assertEqual(
            html,
            '<h2>Título</h2><p>Um <i>texto</i></p><ol><li>a</li><li>b<ol><li>c</li></ol></li></ol>',
        )

    def test_sanitiza_html_perigoso(self):
        html = editorjs_para_html('{"blocks": [{"type": "paragraph", "data": {"text": '
                                  '"<img src=x onerror=alert(1)><script>roubar()</script><a href=\\"javascript:x\\" '
                                  'onclick=\\"y\\">link</a> <a href=\\"https://ok.com\\">ok</a> &lt;b&gt;"}}]}')
        self.assertNotIn('script', html)
        self.assertNotIn('roubar', html)
        self.assertNotIn('onerror', html)
        self.assertNotIn('javascript', html)
        self.assertNotIn('onclick', html)
        self.assertIn('<a href="https://ok.com">ok</a>', html)
        self.assertIn('&lt;b&gt;', html)

    def test_conteudo_invalido_vira_vazio(self):
        for conteudo in (None, {}, 'não é json', {'blocks': 'x'}, []):
            self.assertEqual(editorjs_para_html(conteudo), '')
