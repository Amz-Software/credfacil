"""Endpoints da central de relatórios: permissões, escopo, validação, arquivos e auditoria."""
from itertools import count

from django.test import TestCase

from backoffice_api.models import RegistroAuditoria
from backoffice_api.painel.tests import cenario
from backoffice_api.painel.tests.cenario import dias
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario

BASE = '/api/bo/v1/relatorios/'
VENDAS = 'vendas.can_generate_report_sale'
PAGAMENTOS = 'vendas.can_genarate_report_payments'
_NUMERO = count(1)
PERIODO = {'data_inicial': dias(-90).isoformat(), 'data_final': dias(90).isoformat()}


class BaseRelatorios(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Loja Alfa')
        self.loja_b = criar_loja('Loja Beta')
        self.dados = cenario.montar_carteira(self.loja_a, self.loja_b)
        cenario.criar_analise(self.dados['maria'], status='A', venda=self.dados['venda_maria'])
        cenario.criar_analise(self.dados['ana'], status='EA')

    def cliente(self, *permissoes, lojas=None, **extras):
        lojas = (self.loja_a,) if lojas is None else lojas
        nome = f'usuario{next(_NUMERO)}'
        return cliente_logado(criar_usuario(nome, permissoes=permissoes, lojas=lojas, **extras))


class CatalogoTests(BaseRelatorios):
    def test_sem_permissao_de_relatorio_responde_403(self):
        self.assertEqual(self.cliente().get(BASE + 'catalogo/').status_code, 403)

    def test_lista_so_os_relatorios_permitidos_com_filtros(self):
        corpo = self.cliente(VENDAS).get(BASE + 'catalogo/').json()
        self.assertEqual([r['id'] for r in corpo], ['vendas', 'solicitacoes'])
        filtros = {f['nome']: f for f in corpo[0]['filtros']}
        self.assertEqual(filtros['data_inicial']['tipo'], 'data')
        self.assertEqual([o['rotulo'] for o in filtros['lojas']['opcoes']], ['Loja Alfa'])
        self.assertEqual(filtros['analise_online']['tipo'], 'booleano')
        self.assertEqual(corpo[0]['enderecos']['pdf'], BASE + 'vendas/pdf/')

    def test_relatorios_financeiros_e_excel(self):
        corpo = self.cliente(PAGAMENTOS, 'vendas.can_view_all_payments').get(BASE + 'catalogo/').json()
        self.assertEqual([r['id'] for r in corpo], ['contas_a_receber', 'situacoes', 'parcelas'])
        contas = {f['nome']: f for f in corpo[0]['filtros']}
        self.assertTrue(contas['data_inicial']['obrigatorio'])
        self.assertEqual(len(contas['lojas']['opcoes']), 2)
        self.assertEqual(corpo[2]['enderecos']['excel'], BASE + 'parcelas/excel/')


class PreviaTests(BaseRelatorios):
    def test_sem_permissao_responde_403(self):
        self.assertEqual(self.cliente(PAGAMENTOS).get(BASE + 'vendas/previa/').status_code, 403)
        self.assertEqual(self.cliente(VENDAS).get(BASE + 'parcelas/previa/').status_code, 403)

    def test_vendas_do_escopo_paginadas_com_totais_e_auditoria(self):
        resposta = self.cliente(VENDAS).get(BASE + 'vendas/previa/', {'page_size': 1})
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual((corpo['count'], corpo['page_size'], len(corpo['results'])), (2, 1, 1))
        self.assertEqual(corpo['totais']['total_vendas'], 2)
        self.assertEqual({r['loja'] for r in corpo['results']}, {'Loja Alfa'})
        registro = RegistroAuditoria.objects.get(acao='relatorio_gerado')
        self.assertEqual((registro.dados['relatorio'], registro.dados['formato']), ('vendas', 'previa'))

    def test_loja_fora_do_escopo_no_filtro_responde_400_e_no_cabecalho_403(self):
        cliente = self.cliente(VENDAS)
        resposta = cliente.get(BASE + 'vendas/previa/', {'lojas': self.loja_b.pk})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('lojas', resposta.json()['erro']['campos'])
        self.assertEqual(cliente.get(BASE + 'vendas/previa/', HTTP_X_LOJA=str(self.loja_b.pk)).status_code, 403)

    def test_gerente_e_administrador(self):
        gerente = self.cliente(VENDAS, gerente_de=(self.loja_b,))
        self.assertEqual(gerente.get(BASE + 'vendas/previa/').json()['count'], 5)
        admin = cliente_logado(criar_usuario('admin', permissoes=(VENDAS, 'vendas.can_view_all_stores')))
        corpo = admin.get(BASE + 'vendas/previa/', {'lojas': [self.loja_a.pk, self.loja_b.pk]}).json()
        self.assertEqual(corpo['count'], 5)

    def test_datas_invertidas_e_periodo_obrigatorio_respondem_400(self):
        resposta = self.cliente(VENDAS).get(BASE + 'vendas/previa/', {'data_inicial': '2026-05-10', 'data_final': '2026-05-01'})
        self.assertIn('data_final', resposta.json()['erro']['campos'])
        resposta = self.cliente(PAGAMENTOS).get(BASE + 'contas_a_receber/previa/', {'status': 'atrasado'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('data_inicial', resposta.json()['erro']['campos'])

    def test_solicitacoes_contas_situacoes_e_parcelas(self):
        vendas = self.cliente(VENDAS, 'vendas.can_view_all_stores')
        corpo = vendas.get(BASE + 'solicitacoes/previa/', {'status_solicitacao': 'A'}).json()
        self.assertEqual(corpo['count'], 1)
        self.assertTrue(corpo['results'][0]['cliente'])
        financeiro = self.cliente(PAGAMENTOS, 'vendas.can_view_all_payments')
        contas = financeiro.get(BASE + 'contas_a_receber/previa/', {**PERIODO, 'status': 'atrasado'}).json()
        self.assertEqual(contas['totais']['modo'], 'pagamentos')
        self.assertGreater(contas['count'], 0)
        situacoes = financeiro.get(BASE + 'situacoes/previa/', {'situacoes': 'desativado'}).json()
        self.assertEqual([r['cliente'] for r in situacoes['results']], ['Ana Reis'])
        grade = financeiro.get(BASE + 'parcelas/previa/', {'status': 'quitado'}).json()
        self.assertEqual([r['cliente'] for r in grade['results']], ['João Lima'])

    def test_financeiro_sem_permissao_global_fica_na_propria_loja(self):
        corpo = self.cliente(PAGAMENTOS, lojas=(self.loja_b,)).get(BASE + 'parcelas/previa/').json()
        self.assertEqual({r['loja'] for r in corpo['results']}, {'Loja Beta'})

    def test_post_nao_e_aceito(self):
        self.assertIn(self.cliente(VENDAS).post(BASE + 'vendas/previa/', {}).status_code, (403, 405))


class ArquivosTests(BaseRelatorios):
    def _pdf_ok(self, resposta):
        self.assertEqual(resposta.status_code, 200, getattr(resposta, 'content', b'')[:300])
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))

    def test_pdf_de_cada_relatorio_e_auditado(self):
        vendas = self.cliente(VENDAS)
        self._pdf_ok(vendas.get(BASE + 'vendas/pdf/', HTTP_ACCEPT='application/pdf'))
        self._pdf_ok(vendas.get(BASE + 'solicitacoes/pdf/'))
        financeiro = cliente_logado(criar_usuario('fin', permissoes=(PAGAMENTOS, 'vendas.can_view_all_payments')))
        self._pdf_ok(financeiro.get(BASE + 'contas_a_receber/pdf/', {**PERIODO, 'status': 'todos'}))
        self._pdf_ok(financeiro.get(BASE + 'contas_a_receber/pdf/', {**PERIODO, 'status': 'pago'}))
        self._pdf_ok(financeiro.get(BASE + 'situacoes/pdf/'))
        self._pdf_ok(financeiro.get(BASE + 'parcelas/pdf/'))
        formatos = set(RegistroAuditoria.objects.filter(acao='relatorio_gerado').values_list('dados__relatorio', 'dados__formato'))
        self.assertEqual(formatos, {
            ('vendas', 'pdf'), ('solicitacoes', 'pdf'), ('contas_a_receber', 'pdf'), ('situacoes', 'pdf'), ('parcelas', 'pdf'),
        })

    def test_pdf_sem_permissao_responde_403(self):
        self.assertEqual(self.cliente(VENDAS).get(BASE + 'situacoes/pdf/').status_code, 403)

    def test_excel_de_parcelas(self):
        resposta = self.cliente(PAGAMENTOS).get(BASE + 'parcelas/excel/', {'status': 'atrasado'})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b'PK'))
        self.assertIn('.xlsx', resposta['Content-Disposition'])
        registro = RegistroAuditoria.objects.get(acao='relatorio_gerado')
        self.assertEqual((registro.dados['formato'], registro.dados['filtros']), ('excel', {'status': 'atrasado'}))

    def test_excel_sem_permissao_e_status_invalido(self):
        self.assertEqual(self.cliente(VENDAS).get(BASE + 'parcelas/excel/').status_code, 403)
        resposta = self.cliente(PAGAMENTOS).get(BASE + 'parcelas/excel/', {'status': 'xyz'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('status', resposta.json()['erro']['campos'])
