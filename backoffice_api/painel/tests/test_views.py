"""Endpoints do painel: permissões, escopo de loja, validação, auditoria e métodos."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import AnaliseCreditoCliente

from . import cenario

URL_RESUMO = '/api/bo/v1/painel/resumo/'
URL_GRAFICOS = '/api/bo/v1/painel/graficos/'
URL_PDF = '/api/bo/v1/painel/graficos/relatorio.pdf'


class BaseCarteira(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Loja Alfa')
        self.loja_b = criar_loja('Loja Beta')
        self.dados = cenario.montar_carteira(self.loja_a, self.loja_b)


class ResumoPermissoesTests(BaseCarteira):
    def test_sem_permissoes_de_bloco_so_recebe_a_estrutura(self):
        cliente = cliente_logado(criar_usuario('basico', lojas=(self.loja_a,)))
        resposta = cliente.get(URL_RESUMO)
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertIsNone(corpo['kpis'])
        self.assertIsNone(corpo['analise'])
        self.assertIsNone(corpo['financeiro'])
        self.assertEqual(corpo['atalhos'], [])
        self.assertEqual(corpo['loja'], {'id': self.loja_a.pk, 'nome': 'Loja Alfa'})

    def test_atalhos_seguem_as_permissoes(self):
        user = criar_usuario('atalhos', permissoes=('vendas.view_venda', 'vendas.can_generate_report_sale'), lojas=(self.loja_a,))
        ids = [a['id'] for a in cliente_logado(user).get(URL_RESUMO).json()['atalhos']]
        self.assertEqual(ids, ['vendas', 'relatorios'])

    def test_post_e_recusado(self):
        cliente = cliente_logado(criar_usuario('post', lojas=(self.loja_a,)))
        self.assertIn(cliente.post(URL_RESUMO, {}, format='json').status_code, (403, 405))


class ResumoKpisTests(BaseCarteira):
    def test_kpis_da_loja_do_usuario(self):
        user = criar_usuario('dash', permissoes=('vendas.can_view_your_dashboard',), lojas=(self.loja_a,))
        corpo = cliente_logado(user).get(URL_RESUMO).json()
        kpis = corpo['kpis']
        self.assertEqual(kpis['total_vendas'], 3)  # inclui a cancelada, como a tela inicial
        self.assertEqual(kpis['parcelas_vencidas'], 2)  # a tela inicial também conta a venda cancelada
        self.assertEqual(kpis['valor_vencido'], '200.00')
        self.assertEqual(kpis['grafico_balanco']['rotulos'], ['Pagas', 'Vencidas', 'Desativados'])
        self.assertEqual(kpis['desativados']['total_pagamentos'], 0)

    def test_loja_fora_do_escopo_no_cabecalho_responde_403(self):
        user = criar_usuario('dash', permissoes=('vendas.can_view_your_dashboard',), lojas=(self.loja_a,))
        resposta = cliente_logado(user).get(URL_RESUMO, HTTP_X_LOJA=str(self.loja_b.pk))
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'proibido')

    def test_gerente_soma_as_lojas_e_escolhe_uma_pelo_cabecalho(self):
        user = criar_usuario('gerente', permissoes=('vendas.can_view_your_dashboard',), lojas=(self.loja_a,), gerente_de=(self.loja_b,))
        cliente = cliente_logado(user)
        todas = cliente.get(URL_RESUMO).json()
        so_b = cliente.get(URL_RESUMO, HTTP_X_LOJA=str(self.loja_b.pk)).json()
        self.assertIsNone(todas['loja'])
        self.assertEqual(todas['quantidade_lojas'], 2)
        self.assertEqual(todas['kpis']['total_vendas'], 6)
        self.assertEqual(so_b['kpis']['total_vendas'], 3)
        self.assertEqual(so_b['kpis']['desativados']['total_pagamentos'], 1)

    def test_usuario_sem_permissao_global_pedindo_todas_fica_no_proprio_escopo(self):
        user = criar_usuario('dash', permissoes=('vendas.can_view_your_dashboard',), lojas=(self.loja_a,))
        corpo = cliente_logado(user).get(URL_RESUMO, HTTP_X_LOJA='todas').json()
        self.assertEqual((corpo['quantidade_lojas'], corpo['kpis']['total_vendas']), (1, 3))

    def test_administrador_global_ve_todas(self):
        user = criar_usuario('admin', permissoes=('vendas.can_view_your_dashboard', 'vendas.can_view_all_stores'))
        corpo = cliente_logado(user).get(URL_RESUMO, HTTP_X_LOJA='todas').json()
        self.assertEqual(corpo['quantidade_lojas'], 2)
        self.assertEqual(corpo['kpis']['total_vendas'], 6)


class ResumoFilaCreditoTests(BaseCarteira):
    def setUp(self):
        super().setUp()
        antiga = cenario.criar_analise(self.dados['maria'], status='EA')
        AnaliseCreditoCliente.objects.filter(pk=antiga.pk).update(criado_em=timezone.now() - timedelta(minutes=90))
        recente = cenario.criar_analise(self.dados['joao'], status='EA')
        AnaliseCreditoCliente.objects.filter(pk=recente.pk).update(criado_em=timezone.now() - timedelta(minutes=30))
        cenario.criar_analise(self.dados['ana'], status='A')

    def test_contagem_e_espera_das_lojas_do_usuario(self):
        user = criar_usuario('fila', permissoes=('vendas.view_cliente',), lojas=(self.loja_a,))
        analise = cliente_logado(user).get(URL_RESUMO).json()['analise']
        por_status = {item['status']: item['total'] for item in analise['por_status']}
        self.assertEqual(por_status, {'EA': 2, 'A': 0, 'R': 0, 'C': 0})
        self.assertEqual(analise['em_espera'], 2)
        self.assertEqual(analise['tempo_medio_espera_minutos'], 60)
        self.assertEqual(analise['maior_espera_minutos'], 90)

    def test_quem_ve_todas_as_analises_conta_as_outras_lojas(self):
        user = criar_usuario('analista', permissoes=('vendas.view_cliente', 'vendas.view_all_analise_credito'), lojas=(self.loja_a,))
        analise = cliente_logado(user).get(URL_RESUMO).json()['analise']
        self.assertEqual(analise['total'], 3)

    def test_sem_analises_espera_e_nula(self):
        AnaliseCreditoCliente.objects.all().delete()
        user = criar_usuario('fila', permissoes=('vendas.view_cliente',), lojas=(self.loja_a,))
        analise = cliente_logado(user).get(URL_RESUMO).json()['analise']
        self.assertEqual((analise['total'], analise['tempo_medio_espera_minutos']), (0, None))


class ResumoInadimplenciaTests(BaseCarteira):
    def test_inadimplencia_respeita_a_loja(self):
        user = criar_usuario('fin', permissoes=('vendas.view_pagamento',), lojas=(self.loja_b,))
        financeiro = cliente_logado(user).get(URL_RESUMO).json()['financeiro']
        # Loja B: desativado (1 vencida) + cobrança (1 vencida); devolução fica de fora.
        self.assertEqual(financeiro['parcelas_atrasadas'], 2)
        self.assertEqual(Decimal(financeiro['valor_em_atraso']), Decimal('200.00'))
        self.assertEqual(financeiro['clientes_inadimplentes'], 2)

    def test_todos_os_pagamentos_com_permissao_global(self):
        user = criar_usuario('fin', permissoes=('vendas.view_pagamento', 'vendas.can_view_all_payments'), lojas=(self.loja_b,))
        financeiro = cliente_logado(user).get(URL_RESUMO).json()['financeiro']
        self.assertEqual(financeiro['parcelas_atrasadas'], 3)  # a da venda cancelada não conta


class GraficosTests(BaseCarteira):
    def _cliente(self, *permissoes):
        return cliente_logado(criar_usuario('graficos', permissoes=permissoes))

    def test_sem_permissao_responde_403(self):
        cliente = cliente_logado(criar_usuario('semperm', lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL_GRAFICOS).status_code, 403)

    def test_com_permissao_devolve_series_de_todas_as_lojas(self):
        corpo = self._cliente('vendas.can_view_all_dashboard').get(URL_GRAFICOS).json()
        self.assertEqual(corpo['por_loja']['rotulos'], ['Loja Alfa', 'Loja Beta'])
        self.assertEqual([s['id'] for s in corpo['por_loja']['series']], ['pagas', 'vencidas', 'desativados', 'cobrancas'])
        self.assertIsInstance(corpo['por_loja']['series'][0]['percentuais'][0], float)
        self.assertEqual(corpo['resumo']['clientes_quitados'], 1)
        self.assertIsNone(corpo['por_loja_mes'])
        self.assertEqual(len(corpo['lojas_disponiveis']), 2)

    def test_filtro_de_loja_traz_o_balanco_mensal(self):
        corpo = self._cliente('vendas.can_view_all_dashboard').get(URL_GRAFICOS, {'loja': self.loja_a.pk}).json()
        self.assertEqual(corpo['por_loja']['rotulos'], ['Loja Alfa'])
        self.assertEqual(corpo['filtros']['loja'], self.loja_a.pk)
        self.assertEqual({s['situacao'] for s in corpo['por_loja_mes']['series']}, {'pago', 'vencido', 'a_vencer'})

    def test_cabecalho_x_loja_restringe(self):
        corpo = self._cliente('vendas.can_view_all_dashboard').get(URL_GRAFICOS, HTTP_X_LOJA=str(self.loja_b.pk)).json()
        self.assertEqual(corpo['por_loja']['rotulos'], ['Loja Beta'])

    def test_loja_inexistente_e_datas_invertidas_respondem_400(self):
        cliente = self._cliente('vendas.can_view_all_dashboard')
        resposta = cliente.get(URL_GRAFICOS, {'loja': 99999})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('loja', resposta.json()['erro']['campos'])
        resposta = cliente.get(URL_GRAFICOS, {'data_inicio': '2026-05-10', 'data_fim': '2026-05-01'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('data_fim', resposta.json()['erro']['campos'])
        self.assertEqual(cliente.get(URL_GRAFICOS, {'data_inicio': '10/05/2026'}).status_code, 400)

    def test_post_e_recusado(self):
        self.assertIn(self._cliente('vendas.can_view_all_dashboard').post(URL_GRAFICOS, {}).status_code, (403, 405))


class GraficosPdfTests(BaseCarteira):
    def test_sem_permissao_responde_403(self):
        cliente = cliente_logado(criar_usuario('semperm', permissoes=('vendas.can_view_all_dashboard',)))
        self.assertEqual(cliente.get(URL_PDF).status_code, 403)

    def test_gera_pdf_e_audita(self):
        user = criar_usuario('pdf', permissoes=('vendas.can_generate_dashboard_report',))
        resposta = cliente_logado(user).get(URL_PDF, {'data_inicio': cenario.dias(-90).isoformat()}, HTTP_ACCEPT='application/pdf')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertTrue(resposta.content.startswith(b'%PDF'))
        self.assertIn('attachment;', resposta['Content-Disposition'])
        registro = RegistroAuditoria.objects.get(acao='relatorio_gerado')
        self.assertEqual(registro.usuario, user)
        self.assertEqual(registro.dados['relatorio'], 'painel_graficos')
        self.assertEqual(registro.dados['filtros']['data_inicio'], cenario.dias(-90).isoformat())

    def test_erro_de_validacao_continua_em_json(self):
        user = criar_usuario('pdf', permissoes=('vendas.can_generate_dashboard_report',))
        resposta = cliente_logado(user).get(URL_PDF, {'loja': 'abc'}, HTTP_ACCEPT='application/pdf')
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.json()['erro']['codigo'], 'validacao')
        self.assertFalse(RegistroAuditoria.objects.filter(acao='relatorio_gerado').exists())

    def test_post_e_recusado(self):
        user = criar_usuario('pdf', permissoes=('vendas.can_generate_dashboard_report',))
        self.assertIn(cliente_logado(user).post(URL_PDF, {}).status_code, (403, 405))


class ComodatoTests(BaseCarteira):
    """Filtro `comodato` do dashboard: só vendas de comodato (repasse 0) ou só as comuns."""

    def setUp(self):
        super().setUp()
        from vendas.models import Venda

        Venda.objects.filter(pk=self.dados['venda_joao'].pk).update(comodato=True, repasse_logista=Decimal('0'))

    def test_graficos_filtram_por_comodato(self):
        cliente = cliente_logado(criar_usuario('graficos', permissoes=('vendas.can_view_all_dashboard',)))
        todas = cliente.get(URL_GRAFICOS).json()
        so_comodato = cliente.get(URL_GRAFICOS, {'comodato': 'true'}).json()
        comuns = cliente.get(URL_GRAFICOS, {'comodato': 'false'}).json()
        self.assertIsNone(todas['filtros']['comodato'])
        self.assertTrue(so_comodato['filtros']['comodato'])
        self.assertEqual(so_comodato['resumo']['total_vendas'], 1)
        self.assertEqual(so_comodato['resumo']['total_repasses'], '0.00')
        self.assertEqual(comuns['resumo']['total_vendas'] + 1, todas['resumo']['total_vendas'])
        self.assertEqual(cliente.get(URL_GRAFICOS, {'comodato': 'talvez'}).status_code, 400)

    def test_pdf_com_filtro_de_comodato_e_auditado(self):
        user = criar_usuario('pdf', permissoes=('vendas.can_generate_dashboard_report',))
        resposta = cliente_logado(user).get(URL_PDF, {'comodato': 'true'})
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b'%PDF'))
        registro = RegistroAuditoria.objects.get(acao='relatorio_gerado')
        self.assertTrue(registro.dados['filtros']['comodato'])
