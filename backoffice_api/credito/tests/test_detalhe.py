"""Detalhe, linha do tempo, comprovantes e QR de instalação."""
from backoffice_api.models import RegistroAuditoria
from vendas.models import ConsultaSerasaAcesso, ObservacaoSolicitacao

from .fabricas import CenarioCredito, criar_usuario


class DetalheTests(CenarioCredito):
    def test_detalhe_completo_com_cpf_inteiro(self):
        resposta = self.logar(self.analista).get(self.url(self.sol_a.pk))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados['cliente']['cpf'], '12345678901')
        self.assertEqual(dados['contato_adicional']['nome'], 'Ref Um')
        self.assertEqual(dados['analise']['produto']['nome'], 'Galaxy')
        self.assertEqual(dados['parcelamento']['selecionada']['qtd_vezes'], 10)
        # (1200 - 200) * 1,2 = 1200,00 em 10x de 120,00
        self.assertEqual(dados['parcelamento']['selecionada']['valor_total'], '1200.00')
        self.assertEqual(dados['parcelamento']['selecionada']['valor_parcela'], '120.00')
        self.assertTrue(dados['acoes']['aprovar'])
        self.assertIn('nome', dados['edicao']['campos_editaveis'])
        self.assertEqual(dados['linha_do_tempo'][-1]['tipo'], 'criacao')

    def test_outra_loja_recebe_404(self):
        self.assertEqual(self.logar(self.analista).get(self.url(self.sol_b.pk)).status_code, 404)
        self.assertEqual(self.logar(self.admin).get(self.url(self.sol_b.pk)).status_code, 200)

    def test_serasa_so_para_analista_ou_permissao(self):
        arquivos = self.logar(self.vendedor).get(self.url(self.sol_a.pk)).json()['comprovantes']
        self.assertNotIn('consulta_serasa', [a['campo'] for a in arquivos['arquivos']])
        self.assertIsNone(arquivos['restricao'])
        arquivos = self.logar(self.analista).get(self.url(self.sol_a.pk)).json()['comprovantes']
        self.assertIn('consulta_serasa', [a['campo'] for a in arquivos['arquivos']])

    def test_linha_do_tempo_traz_status_e_observacoes(self):
        analise = self.sol_a.analise_credito
        analise.status = 'A'
        analise.save()
        ObservacaoSolicitacao.objects.create(analise_credito=analise, autor=self.analista, texto='Ligar amanhã')
        eventos = self.logar(self.analista).get(self.url(self.sol_a.pk)).json()['linha_do_tempo']
        tipos = [e['tipo'] for e in eventos]
        self.assertIn('observacao', tipos)
        alteracao = next(e for e in eventos if e['tipo'] == 'alteracao')
        self.assertEqual(alteracao['titulo'], 'Status: Em análise → Aprovado')

    def test_sem_permissao_403_e_delete_405(self):
        self.assertEqual(self.logar(self.sem_permissao).get(self.url(self.sol_a.pk)).status_code, 403)
        self.assertEqual(self.logar(self.admin).delete(self.url(self.sol_a.pk)).status_code, 405)


class ArquivosTests(CenarioCredito):
    def url_arquivo(self, cliente_id, campo):
        return self.url(cliente_id, f'arquivos/{campo}')

    def test_entrega_documento_e_audita(self):
        resposta = self.logar(self.vendedor).get(self.url_arquivo(self.sol_a.pk, 'documento_identificacao_frente'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(resposta.streaming_content).startswith(b'%PDF'))
        registro = RegistroAuditoria.objects.get(acao='documento_acessado')
        self.assertEqual(registro.dados['campo'], 'documento_identificacao_frente')

    def test_serasa_exige_permissao_e_registra_acesso(self):
        url = self.url_arquivo(self.sol_a.pk, 'consulta_serasa')
        self.assertEqual(self.logar(self.vendedor).get(url).status_code, 403)
        resposta = self.logar(self.analista).get(url, HTTP_ACCEPT='application/pdf')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(ConsultaSerasaAcesso.objects.filter(cliente=self.sol_a, tipo='serasa').count(), 1)

    def test_campo_inexistente_ausente_e_outra_loja_404(self):
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.get(self.url_arquivo(self.sol_a.pk, 'senha')).status_code, 404)
        self.assertEqual(cliente.get(self.url_arquivo(self.sol_a.pk, 'comprovante_residencia')).status_code, 404)
        self.assertEqual(cliente.get(self.url_arquivo(self.sol_b.pk, 'foto_cliente')).status_code, 404)

    def test_sem_permissao_403(self):
        url = self.url_arquivo(self.sol_a.pk, 'foto_cliente')
        self.assertEqual(self.logar(self.sem_permissao).get(url).status_code, 403)


class QrInstalacaoTests(CenarioCredito):
    def test_qr_de_instalacao(self):
        dados = self.logar(self.analista).get(self.url(self.sol_a.pk, 'qr-instalacao')).json()
        self.assertTrue(dados['qr_instalacao'].startswith('data:image/png;base64,'))
        self.assertEqual(len(dados['codigo_instalacao']), 16)
        self.assertIsNone(dados['qr_aplicativo'])

    def test_sem_change_cliente_403(self):
        leitor = criar_usuario('leitor', permissoes=('vendas.view_cliente',), lojas=(self.loja_a,))
        self.assertEqual(self.logar(leitor).get(self.url(self.sol_a.pk, 'qr-instalacao')).status_code, 403)
