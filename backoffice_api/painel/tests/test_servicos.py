"""Serviços do painel: mesmos números das telas Django (paridade) e regra dos clientes quitados."""
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from vendas.models import Loja
from vendas.services.kpis import resumo_carteira_loja
from vendas.views.index import DashboardReportPDFView, GraficoTemplateView

from ..servicos.carteira import Periodo
from ..servicos.graficos import calcular_graficos, formatar_graficos
from ..servicos.quitados import clientes_quitados_por_loja
from ..servicos.relatorio_pdf import contexto_relatorio_dashboard
from ..servicos.resumo import kpis_carteira, parcelas_de_contas_a_receber, resumo_inadimplencia
from . import cenario
from .cenario import dias, paga, parcela


def _contexto_antigo_grafico(params: dict) -> dict:
    request = RequestFactory().get('/dash/', params)
    request.user = get_user_model().objects.create_superuser('super_grafico', 'sg@t.local', 'x')
    view = GraficoTemplateView()
    view.setup(request)
    return view.get_context_data()


def _contexto_antigo_pdf(params: dict) -> dict:
    request = RequestFactory().get('/dash/pdf/', params)
    request.user = get_user_model().objects.create_superuser('super_pdf', 'sp@t.local', 'x')
    view = DashboardReportPDFView()
    view.setup(request)
    return view.get_dashboard_data()


class ParidadeGraficosTests(TestCase):
    """O dashboard da API devolve os mesmos números da `GraficoTemplateView`."""

    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja Alfa')
        self.loja_b = Loja.objects.create(nome='Loja Beta')
        Loja.objects.create(nome='Loja Sem Movimento')
        self.dados = cenario.montar_carteira(self.loja_a, self.loja_b)

    def _comparar(self, params: dict, lojas, periodo: Periodo):
        antigo = _contexto_antigo_grafico(params)
        novo = formatar_graficos(calcular_graficos(lojas, periodo, incluir_mensal=lojas.count() == 1))
        resumo = novo['resumo']
        pares = {
            'total_vendas_loja': resumo['total_vendas'],
            'total_de_parcelas_geral': resumo['total_parcelas'],
            'parcelas_vencidas': resumo['parcelas_vencidas'],
            'parcelas_pagas': resumo['parcelas_pagas'],
            'parcelas_a_vencer': resumo['parcelas_a_vencer'],
            'clientes_vencidos': resumo['clientes_vencidos'],
            'clientes_quitados': resumo['clientes_quitados'],
            'valor_total_parcelas': resumo['valor_total_parcelas'],
            'total_pagas': resumo['valor_pago'],
            'total_vencidas': resumo['valor_vencido'],
            'total_a_vencer': resumo['valor_a_vencer'],
            'total_repasses': resumo['total_repasses'],
            'total_desativados_vencidas': resumo['desativados']['valor_vencido'],
            'total_desativados_a_vencer': resumo['desativados']['valor_a_vencer'],
            'qtd_desativados_vencidas': resumo['desativados']['parcelas_vencidas'],
            'qtd_desativados_a_vencer': resumo['desativados']['parcelas_a_vencer'],
            'total_pagamentos_desativados': resumo['desativados']['total_pagamentos'],
            'total_cobranca_vencidas': resumo['cobranca']['valor_vencido'],
            'total_cobranca_a_vencer': resumo['cobranca']['valor_a_vencer'],
            'qtd_cobranca_vencidas': resumo['cobranca']['parcelas_vencidas'],
            'qtd_cobranca_a_vencer': resumo['cobranca']['parcelas_a_vencer'],
            'total_pagamentos_cobranca': resumo['cobranca']['total_pagamentos'],
        }
        for chave, valor in pares.items():
            self.assertEqual(Decimal(antigo[chave]), Decimal(valor), chave)

        lojas_antigas = json.loads(antigo['dados_lojas'])
        self.assertEqual(list(lojas_antigas), novo['por_loja']['rotulos'])
        series = {s['id']: s for s in novo['por_loja']['series']}
        for indice, nome in enumerate(novo['por_loja']['rotulos']):
            esperado = lojas_antigas[nome]
            self.assertAlmostEqual(float(esperado['pct_pagas']), series['pagas']['percentuais'][indice])
            self.assertAlmostEqual(float(esperado['pct_vencidas']), series['vencidas']['percentuais'][indice])
            self.assertAlmostEqual(float(esperado['pct_desativados']), series['desativados']['percentuais'][indice])
            self.assertAlmostEqual(float(esperado['pct_cobrancas']), series['cobrancas']['percentuais'][indice])
            self.assertAlmostEqual(float(esperado['total_pagas']), series['pagas']['valores'][indice])
            self.assertAlmostEqual(float(esperado['total_vencidas']), series['vencidas']['valores'][indice])
        self.assertEqual(
            [nome for nome, _ in sorted(antigo['repasses_por_loja'].items())],
            sorted(item['loja']['nome'] for item in novo['repasses_por_loja']),
        )
        return antigo, novo

    def test_todas_as_lojas_sem_periodo(self):
        antigo, novo = self._comparar({}, Loja.objects.all(), Periodo())
        self.assertIsNone(antigo['dash_mensal_lojas'])
        self.assertIsNone(novo['por_loja_mes'])
        self.assertEqual(novo['resumo']['clientes_quitados'], 1)

    def test_todas_as_lojas_com_periodo(self):
        params = {'data_inicio': dias(-50).isoformat(), 'data_fim': dias(30).isoformat()}
        self._comparar(params, Loja.objects.all(), Periodo(dias(-50), dias(30)))

    def test_uma_loja_traz_o_balanco_mensal_igual_ao_antigo(self):
        params = {'loja': str(self.loja_a.pk)}
        antigo, novo = self._comparar(params, Loja.objects.filter(pk=self.loja_a.pk), Periodo())
        mensal_antigo = json.loads(antigo['dash_mensal_lojas'])['Loja Alfa']
        meses = novo['por_loja_mes']['rotulos']
        self.assertEqual([item['mes'] for item in mensal_antigo], meses)
        series = {s['situacao']: s for s in novo['por_loja_mes']['series']}
        for indice, item in enumerate(mensal_antigo):
            self.assertAlmostEqual(item['pago'], series['pago']['valores'][indice])
            self.assertAlmostEqual(item['vencido'], series['vencido']['valores'][indice])
            self.assertAlmostEqual(item['a_vencer'], series['a_vencer']['valores'][indice])


class ParidadeRelatorioPdfTests(TestCase):
    """O PDF da API recebe o mesmo contexto da `DashboardReportPDFView`."""

    CAMPOS = (
        'total_vendas', 'total_parcelas', 'parcelas_pagas', 'parcelas_vencidas', 'clientes_vencidos',
        'clientes_quitados', 'parcelas_a_vencer', 'total_pagas', 'total_vencidas', 'total_a_vencer',
        'total_desativados_vencidas', 'total_desativados_a_vencer', 'qtd_desativados_vencidas',
        'qtd_desativados_a_vencer', 'total_repasses', 'valor_total_parcelas',
    )

    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja Alfa')
        self.loja_b = Loja.objects.create(nome='Loja Beta')
        Loja.objects.create(nome='Loja Sem Movimento')
        cenario.montar_carteira(self.loja_a, self.loja_b)

    def _comparar(self, params: dict, periodo: Periodo):
        antigo = _contexto_antigo_pdf(params)
        novo = contexto_relatorio_dashboard(Loja.objects.all(), periodo, usuario=None)
        self.assertEqual(list(antigo['dados_por_loja']), list(novo['dados_por_loja']))
        for nome, dados in antigo['dados_por_loja'].items():
            for campo in self.CAMPOS:
                self.assertEqual(Decimal(dados[campo]), Decimal(novo['dados_por_loja'][nome][campo]), f'{nome}.{campo}')
        for campo in ('clientes_vencidos', 'clientes_quitados', 'clientes_quitados_lista'):
            self.assertEqual(antigo[campo], novo[campo], campo)
        return novo

    def test_sem_periodo(self):
        novo = self._comparar({}, Periodo())
        self.assertEqual(novo['clientes_quitados_lista'], [{'nome': 'João Lima', 'lojas': 'Loja Alfa'}])

    def test_com_periodo(self):
        self._comparar({'data_inicio': dias(-50).isoformat(), 'data_fim': dias(15).isoformat()}, Periodo(dias(-50), dias(15)))


class ClientesQuitadosTests(TestCase):
    """Cenários da spec `dashboard-clientes-quitados`."""

    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja Alfa')
        self.loja_b = Loja.objects.create(nome='Loja Beta')
        self.ipx = cenario.tipo_ipx()

    def _pagamento(self, loja, cliente, parcelas, tipo=None):
        venda = cenario.criar_venda(loja, cliente)
        return cenario.criar_pagamento(venda, tipo or self.ipx, '200.00', parcelas)

    def test_cliente_com_dois_financiamentos_quitados_conta_uma_vez_no_total(self):
        cliente = cenario.criar_cliente(self.loja_a, 'Carla')
        p1 = self._pagamento(self.loja_a, cliente, [paga(dias(-30), dias(-30))])
        p2 = self._pagamento(self.loja_b, cliente, [paga(dias(-20), dias(-20))])
        quitados = clientes_quitados_por_loja([p1.pk, p2.pk])
        self.assertEqual(quitados, {self.loja_a.pk: {cliente.pk}, self.loja_b.pk: {cliente.pk}})
        self.assertEqual(set().union(*quitados.values()), {cliente.pk})

    def test_parcela_em_aberto_ou_pagamento_nao_ipx_nao_quitam(self):
        cliente = cenario.criar_cliente(self.loja_a, 'Davi')
        parcial = self._pagamento(self.loja_a, cliente, [paga(dias(-30), dias(-30)), parcela(dias(10))])
        outro_tipo = self._pagamento(self.loja_a, cliente, [paga(dias(-30), dias(-30))], tipo=cenario.tipo_entrada())
        self.assertEqual(clientes_quitados_por_loja([parcial.pk, outro_tipo.pk]), {})

    def test_quitacao_considera_todas_as_parcelas_e_nao_so_as_do_periodo(self):
        cliente = cenario.criar_cliente(self.loja_a, 'Eva')
        pagamento = self._pagamento(self.loja_a, cliente, [paga(dias(-90), dias(-90)), parcela(dias(30))])
        self.assertEqual(clientes_quitados_por_loja([pagamento.pk]), {})


class KpisCarteiraTests(TestCase):
    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja Alfa')
        self.loja_b = Loja.objects.create(nome='Loja Beta')
        cenario.montar_carteira(self.loja_a, self.loja_b)

    def test_uma_loja_repete_o_resumo_da_tela_inicial(self):
        antigo = resumo_carteira_loja(self.loja_a)
        novo = kpis_carteira(Loja.objects.filter(pk=self.loja_a.pk))
        self.assertEqual(novo['total_vendas'], antigo['total_vendas_loja'])
        self.assertEqual(novo['valor_vencido'], antigo['total_vencidas'])
        self.assertEqual(novo['desativados']['total_pagamentos'], antigo['total_pagamentos_desativados'])
        self.assertEqual(novo['grafico_balanco']['valores'], json.loads(antigo['dash'])['data'])

    def test_varias_lojas_somam_os_resumos(self):
        a, b = resumo_carteira_loja(self.loja_a), resumo_carteira_loja(self.loja_b)
        novo = kpis_carteira(Loja.objects.filter(pk__in=[self.loja_a.pk, self.loja_b.pk]))
        self.assertEqual(novo['total_parcelas'], a['total_de_parcelas_geral'] + b['total_de_parcelas_geral'])
        self.assertEqual(novo['valor_pago'], a['total_pagas'] + b['total_pagas'])
        self.assertEqual(sum(novo['grafico_balanco']['valores']) <= 100.01, True)

    def test_sem_lojas_devolve_none(self):
        self.assertIsNone(kpis_carteira(Loja.objects.none()))


class InadimplenciaTests(TestCase):
    def test_soma_o_valor_restante_das_parcelas_vencidas_em_aberto(self):
        loja = Loja.objects.create(nome='Loja Alfa')
        cliente = cenario.criar_cliente(loja, 'Fabio')
        venda = cenario.criar_venda(loja, cliente)
        pagamento = cenario.criar_pagamento(venda, cenario.tipo_ipx(), '300.00', [
            parcela(dias(-10), '100.00', valor_pago='30.00', desconto='10.00'),
            parcela(dias(-5)),
            parcela(dias(5)),
        ])
        devolvida = cenario.criar_pagamento(
            cenario.criar_venda(loja, cliente), cenario.tipo_ipx(), '100.00', [parcela(dias(-3))], devolucao=True,
        )
        resumo = resumo_inadimplencia(parcelas_de_contas_a_receber())
        esperado = sum(p.valor_restante for p in pagamento.parcelas_pagamento.filter(pago=False, data_vencimento__lt=cenario.hoje()))
        self.assertEqual(resumo['valor_em_atraso'], esperado)
        self.assertEqual(resumo['valor_em_atraso'], Decimal('160.00'))
        self.assertEqual((resumo['parcelas_atrasadas'], resumo['pagamentos_em_atraso'], resumo['clientes_inadimplentes']), (2, 1, 1))
        self.assertNotEqual(devolvida.pk, None)
