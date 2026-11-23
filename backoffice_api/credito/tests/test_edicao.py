"""PATCH da solicitação pelo analista (forms de vendas/forms.py)."""
from django.core.files.uploadedfile import SimpleUploadedFile

from backoffice_api.models import RegistroAuditoria
from vendas.models import Venda

from .fabricas import CenarioCredito, png


class EdicaoTests(CenarioCredito):
    def test_patch_parcial_altera_so_o_enviado_e_audita(self):
        resposta = self.logar(self.analista).patch(
            self.url(self.sol_a.pk), {'nome': 'Maria Souza', 'profissao': 'Professora'}, format='json',
        )
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.sol_a.refresh_from_db()
        self.assertEqual(self.sol_a.nome, 'Maria Souza')
        self.assertEqual(self.sol_a.cidade, 'Belém')
        self.assertEqual(resposta.json()['cliente']['profissao'], 'Professora')
        registro = RegistroAuditoria.objects.get(acao='solicitacao_editada')
        self.assertEqual(registro.dados['campos'], ['nome', 'profissao'])

    def test_validacao_do_form_vira_400_com_campos(self):
        resposta = self.logar(self.analista).patch(self.url(self.sol_a.pk), {'cpf': '123'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('cpf', resposta.json()['erro']['campos'])

    def test_contatos_iguais_400(self):
        resposta = self.logar(self.analista).patch(
            self.url(self.sol_a.pk), {'contato_pessoal': '91988887777'}, format='json',
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('contato', resposta.json()['erro']['campos'])

    def test_parcelamento_inexistente_400(self):
        resposta = self.logar(self.analista).patch(self.url(self.sol_a.pk), {'numero_parcelas': '7'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('numero_parcelas', resposta.json()['erro']['campos'])

    def test_upload_valida_tipo_pelo_conteudo(self):
        cliente = self.logar(self.analista)
        texto = SimpleUploadedFile('rg.pdf', b'isto nao e pdf', content_type='application/pdf')
        resposta = cliente.patch(self.url(self.sol_a.pk), {'comprovante_residencia': texto}, format='multipart')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('comprovante_residencia', resposta.json()['erro']['campos'])
        resposta = cliente.patch(self.url(self.sol_a.pk), {'comprovante_residencia': png()}, format='multipart')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.sol_a.comprovantes.refresh_from_db()
        self.assertTrue(self.sol_a.comprovantes.comprovante_residencia)

    def test_campo_sem_permissao_400(self):
        # Vendedor não tem acesso ao Serasa nem ao número autenticador.
        resposta = self.logar(self.vendedor).patch(self.url(self.sol_a.pk), {'restricao': True}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('restricao', resposta.json()['erro']['campos'])

    def test_apos_venda_so_analista_e_produto_travado(self):
        venda = Venda.objects.create(cliente=self.sol_a, vendedor=self.vendedor, loja=self.loja_a, repasse_logista=0)
        analise = self.sol_a.analise_credito
        analise.venda = venda
        analise.status = 'A'
        analise.save()
        resposta = self.logar(self.vendedor).patch(self.url(self.sol_a.pk), {'nome': 'X Y'}, format='json')
        self.assertEqual(resposta.status_code, 403)
        cliente = self.logar(self.analista)
        resposta = cliente.patch(self.url(self.sol_a.pk), {'data_pagamento': '20'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('data_pagamento', resposta.json()['erro']['campos'])
        self.assertEqual(cliente.patch(self.url(self.sol_a.pk), {'bairro': 'Umarizal'}, format='json').status_code, 200)

    def test_sem_permissao_403_e_outra_loja_404(self):
        self.assertEqual(self.logar(self.sem_permissao).patch(self.url(self.sol_a.pk), {}, format='json').status_code, 403)
        self.assertEqual(self.logar(self.analista).patch(self.url(self.sol_b.pk), {}, format='json').status_code, 404)

    def test_put_405(self):
        self.assertEqual(self.logar(self.analista).put(self.url(self.sol_a.pk), {}, format='json').status_code, 405)
