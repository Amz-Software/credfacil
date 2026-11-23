"""Pré-análise rápida."""
from django.core.files.uploadedfile import SimpleUploadedFile

from backoffice_api.models import RegistroAuditoria
from vendas.models import PreAnaliseRapida

from .fabricas import BASE, CenarioCredito, criar_pre_analise, criar_usuario, pdf


class PreAnaliseTests(CenarioCredito):
    def setUp(self):
        super().setUp()
        self.pre_a = criar_pre_analise(self.loja_a, criado_por=self.vendedor)
        self.pre_b = criar_pre_analise(self.loja_b, nome='Lia Costa', cpf='11122233300')

    def url(self, pre_id=None, acao=None):
        if pre_id is None:
            return f'{BASE}/pre-analises/'
        return f'{BASE}/pre-analises/{pre_id}/' + (f'{acao}/' if acao else '')

    def test_lista_com_escopo_e_cpf_mascarado(self):
        dados = self.logar(self.analista).get(self.url()).json()
        self.assertEqual([r['id'] for r in dados['results']], [self.pre_a.pk])
        self.assertEqual(dados['results'][0]['cpf'], '***.654.321-**')
        self.assertEqual(self.logar(self.admin).get(self.url()).json()['count'], 2)
        self.assertEqual(self.logar(self.sem_permissao).get(self.url()).status_code, 403)

    def test_filtros(self):
        cliente = self.logar(self.admin)
        self.assertEqual(cliente.get(self.url(), {'busca': 'Lia'}).json()['count'], 1)
        self.assertEqual(cliente.get(self.url(), {'status': 'A'}).json()['count'], 0)
        self.assertEqual(cliente.get(self.url(), {'status': 'Z'}).status_code, 400)

    def test_detalhe_e_outra_loja(self):
        dados = self.logar(self.analista).get(self.url(self.pre_a.pk)).json()
        self.assertEqual(dados['cpf'], '98765432100')
        self.assertTrue(dados['arquivos'][0]['url'].endswith('/arquivos/foto_rg_frente/'))
        self.assertIsNotNone(dados['consulta_serasa'])
        self.assertIsNone(self.logar(self.vendedor).get(self.url(self.pre_a.pk)).json()['consulta_serasa'])
        self.assertEqual(self.logar(self.analista).get(self.url(self.pre_b.pk)).status_code, 404)

    def test_aprovar_e_nao_decidir_duas_vezes(self):
        cliente = self.logar(self.analista)
        resposta = cliente.post(self.url(self.pre_a.pk, 'aprovar'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['status'], 'A')
        self.assertTrue(RegistroAuditoria.objects.filter(acao='pre_analise_aprovada').exists())
        self.assertEqual(cliente.post(self.url(self.pre_a.pk, 'aprovar')).status_code, 422)
        self.assertEqual(self.logar(self.vendedor).post(self.url(self.pre_a.pk, 'aprovar')).status_code, 403)
        self.assertEqual(cliente.get(self.url(self.pre_a.pk, 'aprovar')).status_code, 405)

    def test_reprovar_exige_motivo(self):
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.post(self.url(self.pre_a.pk, 'reprovar'), {}, format='json').status_code, 400)
        resposta = cliente.post(self.url(self.pre_a.pk, 'reprovar'), {'motivo': 'RG ilegível'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['observacao'], 'RG ilegível')
        self.assertEqual(RegistroAuditoria.objects.get(acao='pre_analise_reprovada').motivo, 'RG ilegível')

    def test_anexar_e_remover_serasa(self):
        cliente = self.logar(self.analista)
        url = self.url(self.pre_a.pk, 'consulta-serasa')
        invalido = SimpleUploadedFile('s.pdf', b'texto', content_type='application/pdf')
        self.assertEqual(cliente.post(url, {'arquivo': invalido}, format='multipart').status_code, 400)
        self.assertEqual(cliente.post(url, {}, format='multipart').status_code, 400)
        resposta = cliente.post(url, {'arquivo': pdf('serasa.pdf')}, format='multipart')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertTrue(resposta.json()['consulta_serasa']['presente'])
        arquivo = cliente.get(self.url(self.pre_a.pk, 'arquivos/consulta_serasa'))
        self.assertEqual(arquivo.status_code, 200)
        self.assertEqual(cliente.delete(url).status_code, 200)
        self.assertEqual(cliente.delete(url).status_code, 404)
        self.assertTrue(RegistroAuditoria.objects.filter(acao='pre_analise_serasa_removida').exists())

    def test_serasa_vendedor_403_e_finalizada_422(self):
        url = self.url(self.pre_a.pk, 'consulta-serasa')
        self.assertEqual(self.logar(self.vendedor).post(url, {'arquivo': pdf()}, format='multipart').status_code, 403)
        PreAnaliseRapida.objects.filter(pk=self.pre_a.pk).update(cliente_gerado=self.sol_a)
        self.assertEqual(self.logar(self.analista).post(url, {'arquivo': pdf()}, format='multipart').status_code, 422)

    def test_arquivo_foto_rg_auditado(self):
        resposta = self.logar(self.vendedor).get(self.url(self.pre_a.pk, 'arquivos/foto_rg_frente'))
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(RegistroAuditoria.objects.filter(acao='documento_acessado', dados__campo='foto_rg_frente').exists())
        self.assertEqual(
            self.logar(self.vendedor).get(self.url(self.pre_a.pk, 'arquivos/consulta_serasa')).status_code, 403,
        )

    def test_relatorio_pdf(self):
        url = f'{BASE}/pre-analises/relatorio.pdf'
        self.assertEqual(self.logar(self.vendedor).get(url).status_code, 403)
        resposta = self.logar(self.analista).get(url, HTTP_ACCEPT='application/pdf')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))
        self.assertEqual(RegistroAuditoria.objects.get(acao='relatorio_pre_analises_gerado').dados['total'], 1)

    def test_relatorio_para_administrador_sem_permissao_extra(self):
        admin = criar_usuario('adm2', grupos=('ADMINISTRADOR',))
        self.assertEqual(self.logar(admin).get(f'{BASE}/pre-analises/relatorio.pdf').status_code, 200)
