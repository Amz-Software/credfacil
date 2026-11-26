"""Comodato nos relatórios: filtro Sim/Não, marca na linha e totais separados (comodato × demais).

Venda de comodato tem repasse 0 ao lojista: o valor financiado fica todo com a IPX.
"""
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.test import TestCase

from backoffice_api.painel.tests import cenario
from backoffice_api.painel.tests.cenario import dias
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import Venda

from ..excel_parcelas import gerar_planilha
from ..pdf import renderizar_template_local
from ..servicos import contas_a_receber, parcelas, situacoes, solicitacoes, vendas
from ..servicos.comum import EscopoRelatorio

BASE = '/api/bo/v1/relatorios/'
VENDAS = 'vendas.can_generate_report_sale'
PAGAMENTOS = 'vendas.can_genarate_report_payments'
TODOS_PAGAMENTOS = 'vendas.can_view_all_payments'
RELATORIOS = ('vendas', 'solicitacoes', 'contas_a_receber', 'situacoes', 'parcelas')


def escopo_total() -> EscopoRelatorio:
    return EscopoRelatorio(lojas_escolhidas=(), aplicar_escopo=lambda qs, campo: qs)


class CarteiraComComodato(TestCase):
    """Carteira do painel com a venda do João (Loja Alfa) virando comodato (repasse 0)."""

    def setUp(self):
        self.loja_a = criar_loja('Loja Alfa')
        self.loja_b = criar_loja('Loja Beta')
        self.dados = cenario.montar_carteira(self.loja_a, self.loja_b)
        Venda.objects.filter(pk=self.dados['venda_joao'].pk).update(comodato=True, repasse_logista=Decimal('0'))
        self.venda_joao = Venda.objects.get(pk=self.dados['venda_joao'].pk)
        cenario.criar_analise(self.dados['joao'], status='A', venda=self.venda_joao, comodato=True)
        cenario.criar_analise(self.dados['maria'], status='A', venda=self.dados['venda_maria'])


class VendasComodatoTests(CarteiraComComodato):
    def test_filtro_sim_nao_e_marca_na_linha(self):
        so_comodato = vendas.linhas(vendas.consultar({'comodato': True}, escopo_total()))
        self.assertEqual([(l['cliente'], l['comodato']) for l in so_comodato], [('João Lima', True)])
        comuns = vendas.linhas(vendas.consultar({'comodato': False}, escopo_total()))
        self.assertEqual(len(comuns), 4)
        self.assertFalse(any(l['comodato'] for l in comuns))
        self.assertEqual(vendas.consultar({'comodato': None}, escopo_total()).count(), 5)

    def test_juros_do_comodato_usam_o_valor_financiado_como_o_modelo(self):
        linha = vendas.linhas(vendas.consultar({'comodato': True}, escopo_total()))[0]
        self.assertEqual(linha['valor_repasse'], Decimal('0'))
        self.assertEqual(linha['valor_juros'], self.venda_joao.juros)

    def test_totais_separam_comodato_das_vendas_comuns(self):
        totais = vendas.totais(vendas.consultar({}, escopo_total()))
        comuns = Venda.objects.filter(is_deleted=False, comodato=False)
        self.assertEqual(totais['total_vendas'], 5)
        self.assertEqual((totais['comodato_quantidade'], totais['demais_quantidade']), (1, 4))
        self.assertEqual(totais['comodato_valor'], self.venda_joao.valor_total_venda)
        self.assertEqual(totais['demais_valor'], sum(v.valor_total_venda for v in comuns))
        self.assertEqual(totais['comodato_ipx'], self.venda_joao.valor_financiado)
        self.assertEqual(totais['demais_repasse'], sum(v.repasse_logista for v in comuns))
        self.assertEqual(totais['total_repasse'], totais['demais_repasse'])  # comodato não tem repasse
        self.assertEqual(totais['total_juros'], sum(v.juros for v in Venda.objects.filter(is_deleted=False)))


class SolicitacoesComodatoTests(CarteiraComComodato):
    def test_filtro_linha_e_totais(self):
        consulta = solicitacoes.consultar({'comodato': True}, escopo_total())
        linhas = solicitacoes.linhas(consulta)
        self.assertEqual([(l['cliente'], l['comodato']) for l in linhas], [('João Lima', True)])
        totais = solicitacoes.totais(consulta)
        self.assertEqual(totais['total_solicitacoes'], 1)
        self.assertEqual((totais['comodato_quantidade'], totais['demais_quantidade']), (1, 0))
        self.assertEqual(totais['comodato_ipx'], self.venda_joao.valor_financiado)
        self.assertEqual(totais['demais_repasse'], Decimal('0'))
        comuns = solicitacoes.linhas(solicitacoes.consultar({'comodato': False}, escopo_total()))
        self.assertNotIn('João Lima', {l['cliente'] for l in comuns})
        self.assertFalse(any(l['comodato'] for l in comuns))


class ContasAReceberComodatoTests(CarteiraComComodato):
    PERIODO = {'data_inicial': dias(-90), 'data_final': dias(90)}

    def test_modo_pagamentos(self):
        filtros = {**self.PERIODO, 'status': {'todos'}}
        consulta = contas_a_receber.consultar(filtros, escopo_total())
        totais = contas_a_receber.totais(consulta, filtros)
        self.assertEqual(totais['comodato_quantidade'], 1)
        self.assertEqual(totais['comodato_valor'], Decimal('200.00'))
        self.assertEqual(totais['comodato_valor'] + totais['demais_valor'], totais['total'])
        linhas = contas_a_receber.linhas(contas_a_receber.consultar({**filtros, 'comodato': True}, escopo_total()))
        self.assertEqual([(l['cliente'], l['comodato']) for l in linhas], [('João Lima', True)])

    def test_modo_parcelas_pagas(self):
        filtros = {'data_inicial': dias(-45), 'data_final': dias(0), 'status': {'pago'}}
        totais = contas_a_receber.totais(contas_a_receber.consultar(filtros, escopo_total()), filtros)
        self.assertEqual(totais['comodato_quantidade'], 1)
        self.assertEqual(totais['comodato_valor'] + totais['demais_valor'], totais['total_pago'])
        sem_comodato = contas_a_receber.consultar({**filtros, 'comodato': False}, escopo_total())
        self.assertNotIn('João Lima', {l['cliente'] for l in contas_a_receber.linhas(sem_comodato)})


class SituacoesComodatoTests(CarteiraComComodato):
    def test_filtro_e_quantidades(self):
        totais = situacoes.totais(situacoes.consultar({}, escopo_total()))
        self.assertEqual(totais['comodato_quantidade'], 1)
        self.assertEqual(totais['comodato_quantidade'] + totais['demais_quantidade'], totais['quantidade'])
        linhas = situacoes.linhas(situacoes.consultar({'comodato': True}, escopo_total()))
        self.assertEqual([(l['cliente'], l['comodato']) for l in linhas], [('João Lima', True)])


class ParcelasComodatoTests(CarteiraComComodato):
    def test_filtro_totais_e_coluna_na_planilha(self):
        todas = parcelas.linhas(parcelas.consultar({}, escopo_total()))
        totais = parcelas.totais(parcelas.consultar({}, escopo_total()))
        self.assertEqual((totais['comodato_quantidade'], totais['comodato_valor']), (1, Decimal('200.00')))
        self.assertEqual(totais['comodato_valor'] + totais['demais_valor'], totais['total'])
        so_comodato = parcelas.linhas(parcelas.consultar({'comodato': True}, escopo_total()))
        self.assertEqual([(l['cliente'], l['comodato']) for l in so_comodato], [('João Lima', True)])

        planilha = openpyxl.load_workbook(BytesIO(gerar_planilha(todas))).active
        self.assertEqual(planilha['D5'].value, 'Comodato')
        por_cliente = {planilha.cell(row=r, column=2).value: planilha.cell(row=r, column=4).value for r in range(6, 6 + len(todas))}
        self.assertEqual(por_cliente['João Lima'], 'Sim')
        self.assertEqual(por_cliente['Maria Souza'], 'Não')


class EndpointsComodatoTests(CarteiraComComodato):
    def _cliente(self, *permissoes):
        return cliente_logado(criar_usuario('comodato', permissoes=permissoes, lojas=(self.loja_a,)))

    def test_catalogo_tem_o_filtro_em_todos_os_relatorios(self):
        corpo = self._cliente(VENDAS, PAGAMENTOS, TODOS_PAGAMENTOS).get(BASE + 'catalogo/').json()
        self.assertEqual([r['id'] for r in corpo], list(RELATORIOS))
        for relatorio in corpo:
            filtro = next(f for f in relatorio['filtros'] if f['nome'] == 'comodato')
            self.assertEqual((filtro['tipo'], filtro['rotulo']), ('booleano', 'Comodato'))
            self.assertEqual([o['rotulo'] for o in filtro['opcoes']], ['Sim', 'Não'])

    def test_previa_filtra_marca_e_separa_totais(self):
        cliente = self._cliente(VENDAS)
        corpo = cliente.get(BASE + 'vendas/previa/', {'comodato': 'true'}).json()
        self.assertEqual(corpo['count'], 1)
        self.assertTrue(corpo['results'][0]['comodato'])
        self.assertEqual(corpo['filtros'], {'comodato': True})
        self.assertEqual(corpo['totais']['comodato_quantidade'], 1)
        self.assertEqual(corpo['totais']['comodato_ipx'], '1200.00')
        self.assertEqual(corpo['totais']['demais_repasse'], '0.00')
        comuns = cliente.get(BASE + 'vendas/previa/', {'comodato': 'false'}).json()
        self.assertEqual(comuns['count'], 1)
        self.assertFalse(comuns['results'][0]['comodato'])

    def test_totais_de_cada_relatorio_trazem_comodato(self):
        cliente = self._cliente(VENDAS, PAGAMENTOS, TODOS_PAGAMENTOS)
        periodo = {'data_inicial': dias(-90).isoformat(), 'data_final': dias(90).isoformat(), 'status': 'todos'}
        for relatorio in RELATORIOS:
            params = periodo if relatorio == 'contas_a_receber' else {}
            corpo = cliente.get(BASE + f'{relatorio}/previa/', params).json()
            self.assertIn('comodato_quantidade', corpo['totais'], relatorio)
            self.assertIn('demais_quantidade', corpo['totais'], relatorio)
            self.assertTrue(all('comodato' in linha for linha in corpo['results']), relatorio)

    def test_pdfs_com_filtro_de_comodato(self):
        cliente = self._cliente(VENDAS, PAGAMENTOS, TODOS_PAGAMENTOS)
        periodo = {'data_inicial': dias(-90).isoformat(), 'data_final': dias(90).isoformat(), 'status': 'todos'}
        for relatorio in RELATORIOS:
            params = {**(periodo if relatorio == 'contas_a_receber' else {}), 'comodato': 'true'}
            resposta = cliente.get(BASE + f'{relatorio}/pdf/', params)
            self.assertEqual(resposta.status_code, 200, relatorio)
            self.assertTrue(resposta.content.startswith(b'%PDF'), relatorio)

    def test_valor_invalido_responde_400(self):
        resposta = self._cliente(VENDAS).get(BASE + 'vendas/previa/', {'comodato': 'talvez'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('comodato', resposta.json()['erro']['campos'])


class BlocoComodatoNoPdfTests(TestCase):
    """O bloco de totais de comodato só sai no PDF quando o resultado tem comodato."""

    TEMPLATES = {
        'vendas': 'relatorio_vendas.html',
        'solicitacoes': 'relatorio_solicitacoes.html',
        'parcelas': 'relatorio_parcelas.html',
        'contas_a_receber': 'relatorio_contas_a_receber.html',
        'situacoes': 'relatorio_situacoes.html',
    }

    def _html(self, template: str, comodato_quantidade: int) -> str:
        totais = {
            'quantidade': 3, 'comodato_quantidade': comodato_quantidade, 'comodato_valor': Decimal('100'),
            'demais_quantidade': 3 - comodato_quantidade, 'demais_valor': Decimal('200'),
            'comodato_ipx': Decimal('90'), 'demais_repasse': Decimal('150'), 'modo': 'pagamentos',
        }
        return renderizar_template_local(template, {'linhas': [], 'totais': totais, 'filtros': {}})

    def test_sem_comodato_nao_mostra_o_bloco(self):
        for relatorio, template in self.TEMPLATES.items():
            self.assertNotIn('class="comodato-resumo"', self._html(template, 0), relatorio)

    def test_com_comodato_mostra_o_bloco(self):
        for relatorio, template in self.TEMPLATES.items():
            self.assertIn('class="comodato-resumo"', self._html(template, 1), relatorio)
