"""Comprovantes (upload, download, exclusão), contatos e BO (prévia e PDF)."""
import shutil
import tempfile
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import ComprovanteParcela, Contato, ComprovanteParcela as Comprovante

from .fabricas import URL_BASE, criar_conta, parcelas_de, ultima_auditoria

ANALISTA = ('ANALISTA',)
PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
MEDIA_TESTE = tempfile.mkdtemp(prefix='bo_financeiro_')


def pdf(nome='comprovante.pdf', conteudo=PDF):
    return SimpleUploadedFile(nome, conteudo, content_type='application/pdf')


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class ComprovantesTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)

    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.parcela = parcelas_de(self.conta)[0]
        self.url_upload = f'{URL_BASE}parcelas/{self.parcela.pk}/comprovantes/'

    def _cliente(self, permissoes=('vendas.change_pagamento', 'vendas.view_pagamento'), grupos=ANALISTA):
        return cliente_logado(criar_usuario('ana', permissoes=permissoes, grupos=grupos, lojas=(self.loja,)))

    def test_upload_download_e_exclusao_auditados(self):
        cliente = self._cliente()
        resposta = cliente.post(self.url_upload, {'arquivo': pdf(), 'observacao': 'PIX 10/11'}, format='multipart')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        dados = resposta.json()
        self.assertTrue(dados['url_arquivo'].startswith('/api/bo/v1/financeiro/comprovantes/'))
        self.assertNotIn('mediafiles', str(dados))
        self.assertIsNotNone(ultima_auditoria('comprovante_anexado'))

        arquivo = cliente.get(dados['url_arquivo'])
        self.assertEqual(arquivo.status_code, 200)
        self.assertEqual(b''.join(arquivo.streaming_content), PDF)
        self.assertIsNotNone(ultima_auditoria('comprovante_acessado'))

        detalhe = cliente.get(f'{URL_BASE}contas-a-receber/{self.conta.pk}/').json()
        self.assertEqual(detalhe['parcelas'][0]['comprovantes'][0]['id'], dados['id'])

        self.assertEqual(cliente.delete(f'{URL_BASE}comprovantes/{dados["id"]}/').status_code, 204)
        self.assertFalse(ComprovanteParcela.objects.filter(pk=dados['id']).exists())
        self.assertIsNotNone(ultima_auditoria('comprovante_removido'))

    def test_conteudo_extensao_e_tamanho_validados(self):
        cliente = self._cliente()
        falso = cliente.post(self.url_upload, {'arquivo': pdf(conteudo=b'MZ executavel')}, format='multipart')
        self.assertEqual(falso.status_code, 400)
        self.assertIn('arquivo', falso.json()['erro']['campos'])
        exe = cliente.post(self.url_upload, {'arquivo': pdf('virus.exe')}, format='multipart')
        self.assertIn('arquivo', exe.json()['erro']['campos'])
        grande = pdf(conteudo=PDF + b'0' * (Comprovante.TAMANHO_MAXIMO_BYTES + 1))
        self.assertEqual(cliente.post(self.url_upload, {'arquivo': grande}, format='multipart').status_code, 400)

    def test_permissoes_e_escopo(self):
        sem_grupo = self._cliente(grupos=())
        self.assertEqual(sem_grupo.post(self.url_upload, {'arquivo': pdf()}, format='multipart').status_code, 403)
        outra = parcelas_de(criar_conta(criar_loja('B'), cpf='98765432100'))[0]
        cliente = cliente_logado(criar_usuario('ana2', permissoes=('vendas.change_pagamento',), grupos=ANALISTA,
                                               lojas=(self.loja,)))
        resposta = cliente.post(f'{URL_BASE}parcelas/{outra.pk}/comprovantes/', {'arquivo': pdf()},
                                format='multipart')
        self.assertEqual(resposta.status_code, 404)
        comprovante = ComprovanteParcela(parcela=self.parcela, arquivo=pdf())
        comprovante.save()
        # Download exige view_pagamento.
        self.assertEqual(cliente.get(f'{URL_BASE}comprovantes/{comprovante.pk}/arquivo/').status_code, 403)


class ContatosTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.url = f'{URL_BASE}contas-a-receber/{self.conta.pk}/contatos/'

    def test_criar_exige_permissao_e_valida(self):
        sem = cliente_logado(criar_usuario('sem', lojas=(self.loja,)))
        self.assertEqual(sem.post(self.url, {'data': '2026-11-20'}, format='json').status_code, 403)
        cliente = cliente_logado(criar_usuario('fin', permissoes=('vendas.add_contato',), lojas=(self.loja,)))
        self.assertIn('data', cliente.post(self.url, {'data': 'ontem'}, format='json').json()['erro']['campos'])
        resposta = cliente.post(self.url, {'data': '2026-11-20', 'observacao': 'Sem resposta'}, format='json')
        self.assertEqual(resposta.status_code, 201)
        contato = Contato.objects.get(pk=resposta.json()['id'])
        self.assertEqual(contato.cliente_id, self.conta.venda.cliente_id)

    def test_editar_so_contato_do_cliente(self):
        contato = Contato.objects.create(cliente=self.conta.venda.cliente, data=date.today(), observacao='a')
        alheio = criar_conta(self.loja, cpf='98765432100')
        contato_alheio = Contato.objects.create(cliente=alheio.venda.cliente, data=date.today())
        cliente = cliente_logado(criar_usuario('fin', permissoes=('vendas.change_contato',), lojas=(self.loja,)))
        resposta = cliente.patch(f'{self.url}{contato.pk}/', {'observacao': 'Ligou'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        contato.refresh_from_db()
        self.assertEqual(contato.observacao, 'Ligou')
        self.assertEqual(cliente.patch(f'{self.url}{contato_alheio.pk}/', {'observacao': 'x'}, format='json')
                         .status_code, 404)


class BoTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.url = f'{URL_BASE}contas-a-receber/{self.conta.pk}/bo/'
        user = criar_usuario('ana', permissoes=('financeiro.add_notificacaobo',), grupos=ANALISTA, lojas=(self.loja,))
        self.cliente = cliente_logado(user)

    def test_sem_grupo_recebe_403(self):
        user = criar_usuario('fin', permissoes=('financeiro.add_notificacaobo',), lojas=(self.loja,))
        self.assertEqual(cliente_logado(user).get(f'{self.url}previa/').status_code, 403)

    def test_previa_traz_referencias_padrao(self):
        Contato.objects.create(cliente=self.conta.venda.cliente, data=date.today(), observacao='Irmã: 91988887777')
        resposta = self.cliente.get(f'{self.url}previa/')
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertIn('Irmã: 91988887777', dados['referencias_padrao'])
        self.assertEqual(dados['cliente']['cpf_exibicao'], '123.***.***-01')

    def test_sem_parcela_vencida_recebe_422(self):
        em_dia = criar_conta(self.loja, cpf='98765432100', primeira=date.today() + timedelta(days=5))
        resposta = self.cliente.get(f'{URL_BASE}contas-a-receber/{em_dia.pk}/bo/previa/')
        self.assertEqual(resposta.status_code, 422)

    def test_pdf_gerado_e_auditado(self):
        resposta = self.cliente.post(f'{self.url}pdf/', {'referencias_personais': '1. Mãe - 9199'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))
        self.assertTrue(ultima_auditoria('bo_gerado').dados['referencias_editadas'])
        self.assertEqual(self.cliente.get(f'{self.url}pdf/').status_code, 405)
