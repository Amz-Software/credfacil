"""Serviços dos relatórios: valores calculados no banco batem com as regras dos modelos e das folhas antigas."""
from decimal import Decimal

from django.test import TestCase

from backoffice_api.painel.tests import cenario
from backoffice_api.painel.tests.cenario import dias, paga, parcela
from vendas.models import Loja, Pagamento, Venda

from ..excel_parcelas import gerar_planilha
from ..servicos import contas_a_receber, parcelas, situacoes, solicitacoes, vendas
from ..servicos.comum import EscopoRelatorio


def escopo_total() -> EscopoRelatorio:
    return EscopoRelatorio(lojas_escolhidas=(), aplicar_escopo=lambda qs, campo: qs)


class CarteiraMixin:
    def setUp(self):
        self.loja_a = Loja.objects.create(nome='Loja Alfa')
        self.loja_b = Loja.objects.create(nome='Loja Beta')
        self.dados = cenario.montar_carteira(self.loja_a, self.loja_b)


class VendasTests(CarteiraMixin, TestCase):
    def test_valores_da_linha_batem_com_as_propriedades_de_venda(self):
        consulta = vendas.consultar({}, escopo_total())
        for linha in vendas.linhas(consulta):
            venda = Venda.objects.get(pk=linha['id'])
            self.assertEqual(linha['valor_total'], venda.pagamentos_valor_total)
            self.assertEqual(linha['valor_entrada'], venda.valor_entrada_cliente)
            self.assertEqual(linha['valor_juros'], venda.juros)
            self.assertEqual(linha['parcelas'], venda.qtd_total_parcelas())
            self.assertEqual(linha['pagamento_bloqueado'], venda.possui_pagamento_bloqueado())

    def test_totais_e_venda_cancelada_fora(self):
        consulta = vendas.consultar({}, escopo_total())
        totais = vendas.totais(consulta)
        ativas = Venda.objects.filter(is_deleted=False)
        self.assertEqual(totais['total_vendas'], ativas.count())
        self.assertEqual(totais['total_valor'], sum(v.valor_total_venda for v in ativas))
        self.assertEqual(totais['total_juros'], sum(v.juros for v in ativas))
        self.assertEqual(totais['total_repasse'], sum(v.repasse_logista for v in ativas))

    def test_filtro_de_lojas_e_de_serasa(self):
        escopo = EscopoRelatorio(lojas_escolhidas=(self.loja_b,), aplicar_escopo=lambda qs, campo: qs)
        self.assertEqual({l['loja'] for l in vendas.linhas(vendas.consultar({}, escopo))}, {'Loja Beta'})
        self.assertEqual(vendas.consultar({'analise_serasa': {'true'}}, escopo_total()).count(), 0)


class SolicitacoesTests(CarteiraMixin, TestCase):
    def test_linha_usa_a_venda_da_analise_e_filtra_status(self):
        cenario.criar_analise(self.dados['maria'], status='A', venda=self.dados['venda_maria'])
        cenario.criar_analise(self.dados['ana'], status='R')
        consulta = solicitacoes.consultar({'status_solicitacao': {'A'}}, escopo_total())
        linhas = solicitacoes.linhas(consulta)
        self.assertEqual(len(linhas), 1)
        self.assertTrue(linhas[0]['venda_gerada'])
        self.assertEqual(linhas[0]['valor_juros'], self.dados['venda_maria'].juros)
        self.assertEqual(solicitacoes.totais(consulta)['total_solicitacoes'], 1)

    def test_venda_realizada_falso(self):
        cenario.criar_analise(self.dados['ana'], status='R')
        consulta = solicitacoes.consultar({'venda_realizada': False}, escopo_total())
        rotulos = [l['status_solicitacao_rotulo'] for l in solicitacoes.linhas(consulta)]
        # Como na folha atual, cliente sem análise também entra em "venda realizada = não".
        self.assertIn('Reprovada', rotulos)
        self.assertNotIn('Aprovada', rotulos)


class ContasAReceberTests(CarteiraMixin, TestCase):
    PERIODO = {'data_inicial': dias(-90), 'data_final': dias(90)}

    def test_valores_por_pagamento_batem_com_os_metodos_do_modelo(self):
        consulta = contas_a_receber.consultar({**self.PERIODO, 'status': {'todos'}}, escopo_total())
        self.assertTrue(consulta.exists())
        for pagamento in consulta:
            modelo = Pagamento.objects.get(pk=pagamento.pk)
            self.assertEqual(pagamento.valor_atrasado_calc, modelo.valor_atrasado())
            self.assertEqual(pagamento.valor_a_vencer_calc, modelo.valor_a_vencer())
            self.assertEqual(pagamento.valor_atual_a_vencer_calc, modelo.valor_atual_a_vencer())
            self.assertEqual(pagamento.valor_pago_ultimo_calc, modelo.valor_pago_ultimo())
            self.assertEqual(pagamento.valor_total_parcelas_calc, modelo.valor_total_parcelas())
            self.assertEqual(pagamento.parcelas_totais_calc, modelo.parcelas_totais())
            self.assertEqual(pagamento.valor_quitado_calc, modelo.valor_quitado())
            atrasada = modelo.parcelas_pagamento.filter(pago=False, data_vencimento__lt=cenario.hoje()).order_by('data_vencimento').first()
            self.assertEqual(pagamento.ultimo_vencimento, atrasada.data_vencimento if atrasada else None)

    def test_so_pago_lista_parcelas_pagas_no_periodo(self):
        filtros = {'data_inicial': dias(-45), 'data_final': dias(0), 'status': {'pago'}}
        consulta = contas_a_receber.consultar(filtros, escopo_total())
        linhas = contas_a_receber.linhas(consulta)
        self.assertTrue(all(l['parcela_id'] for l in linhas))
        totais = contas_a_receber.totais(consulta, filtros)
        self.assertEqual(totais['modo'], 'parcelas')
        self.assertEqual(totais['total_pago'], sum(l['valor_pago'] for l in linhas))

    def test_status_atrasado_filtra_pelo_vencimento_em_atraso(self):
        filtros = {**self.PERIODO, 'status': {'atrasado'}}
        linhas = contas_a_receber.linhas(contas_a_receber.consultar(filtros, escopo_total()))
        self.assertTrue(linhas)
        self.assertTrue(all('ATRASADO' in l['situacoes'] for l in linhas))
        self.assertNotIn('Lia Costa', {l['cliente'] for l in linhas})  # devolução fica fora


class SituacoesTests(CarteiraMixin, TestCase):
    def test_situacao_e_ultimo_contato(self):
        from vendas.models import Contato

        Contato.objects.create(cliente=self.dados['pedro'], data=dias(-1), observacao='Prometeu pagar')
        linhas = situacoes.linhas(situacoes.consultar({'situacoes': {'flag_atrasado'}}, escopo_total()))
        self.assertEqual([l['cliente'] for l in linhas], ['Pedro Alves'])
        self.assertEqual(linhas[0]['situacoes'], ['Cobrança'])
        self.assertEqual(linhas[0]['ultimo_contato']['observacao'], 'Prometeu pagar')


class ParcelasTests(CarteiraMixin, TestCase):
    def test_grade_e_totais_e_planilha(self):
        consulta = parcelas.consultar({'status': 'atrasado'}, escopo_total())
        linhas = parcelas.linhas(consulta)
        maria = next(l for l in linhas if l['cliente'] == 'Maria Souza')
        self.assertEqual([p['situacao'] for p in maria['parcelas']], ['pago', 'atrasado', 'a_vencer', 'a_vencer'])
        self.assertEqual(maria['total_pago'], Decimal('90.00'))
        self.assertEqual(maria['total_atrasado'], Decimal('100.00'))
        self.assertEqual(parcelas.totais(consulta)['quantidade'], len(linhas))
        self.assertTrue(gerar_planilha(linhas).startswith(b'PK'))

    def test_busca_por_cpf(self):
        consulta = parcelas.consultar({'busca': self.dados['joao'].cpf}, escopo_total())
        self.assertEqual([l['cliente'] for l in parcelas.linhas(consulta)], ['João Lima'])

    def test_vencimento_no_periodo(self):
        consulta = parcelas.consultar({'data_inicial': dias(30), 'data_final': dias(45)}, escopo_total())
        # Como no filtro atual, início e fim podem casar com parcelas diferentes do mesmo pagamento.
        self.assertEqual({l['cliente'] for l in parcelas.linhas(consulta)}, {'Ana Reis', 'Maria Souza'})


class RecursosDoPdfTests(TestCase):
    def test_so_le_estaticos_locais(self):
        from ..pdf import RecursoBloqueado, buscar_recurso_local

        logo = buscar_recurso_local('https://relatorio.local/static/images/IPIX.png')
        self.assertEqual(logo['mime_type'], 'image/png')
        for url in ('http://169.254.169.254/latest/meta-data', 'https://relatorio.local/static/../core/settings.py',
                    'file:///etc/passwd'):
            with self.assertRaises(RecursoBloqueado):
                buscar_recurso_local(url)
