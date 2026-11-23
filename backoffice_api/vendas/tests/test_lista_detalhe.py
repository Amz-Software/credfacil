"""Lista e detalhe de vendas: permissão, escopo de loja, filtros e formato."""
from rest_framework.test import APIClient

from django.test import TestCase

from .fabricas import URL, CenarioVendas, cliente_logado, criar_usuario, url_venda


class ListaVendasTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda_a = self.criar_venda_manual()
        self.venda_b = self.criar_venda_manual(self.loja_b, cpf='11122233344', nome='Pedro B', imei='350000000000002')
        self.usuario_a = criar_usuario('usuario_a', permissoes=('vendas.view_venda',), lojas=(self.loja_a,))

    def ids(self, resposta):
        return [v['id'] for v in resposta.json()['results']]

    def test_anonimo_recebe_401(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_sem_permissao_recebe_403(self):
        resposta = cliente_logado(criar_usuario('sem', lojas=(self.loja_a,))).get(URL)
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'proibido')

    def test_usuario_comum_ve_so_a_propria_loja_com_cpf_mascarado(self):
        resposta = cliente_logado(self.usuario_a).get(URL)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.ids(resposta), [self.venda_a.pk])
        item = resposta.json()['results'][0]
        self.assertEqual(item['cpf_mascarado'], '***.456.789-**')
        self.assertEqual(item['situacao'], 'ativa')
        self.assertEqual(item['origem'], 'manual')
        self.assertEqual(item['total'], '1000.00')
        self.assertNotIn('cpf', item['cliente'])

    def test_filtro_loja_e_ignorado_sem_permissao_global(self):
        resposta = cliente_logado(self.usuario_a).get(URL, {'loja': self.loja_b.pk})
        self.assertEqual(self.ids(resposta), [self.venda_a.pk])

    def test_gerente_ve_lojas_gerenciadas_e_x_loja_fora_do_escopo_da_403(self):
        gerente = criar_usuario('gerente', permissoes=('vendas.view_venda',), gerente_de=(self.loja_b,))
        cliente = cliente_logado(gerente)
        self.assertEqual(self.ids(cliente.get(URL)), [self.venda_b.pk])
        self.assertEqual(cliente.get(URL, HTTP_X_LOJA=str(self.loja_a.pk)).status_code, 403)

    def test_global_ve_todas_e_filtra_por_loja(self):
        admin = criar_usuario('admin', permissoes=('vendas.view_venda', 'vendas.can_view_all_sales'))
        cliente = cliente_logado(admin)
        self.assertEqual(sorted(self.ids(cliente.get(URL))), sorted([self.venda_a.pk, self.venda_b.pk]))
        self.assertEqual(self.ids(cliente.get(URL, {'loja': self.loja_b.pk})), [self.venda_b.pk])

    def test_filtros_de_situacao_origem_e_busca(self):
        analise = self.criar_venda_da_analise()
        self.venda_a.is_trocado = True
        self.venda_a.save()
        cancelada = self.criar_venda_manual(cpf='55566677788', nome='Ana C', imei='350000000000003')
        cancelada.is_deleted = True
        cancelada.save()
        cliente = cliente_logado(self.usuario_a)
        self.assertEqual(self.ids(cliente.get(URL, {'canceladas': 'true'})), [cancelada.pk])
        self.assertEqual(len(self.ids(cliente.get(URL, {'canceladas': 'todas'}))), 3)
        self.assertEqual(self.ids(cliente.get(URL, {'trocadas': 'true'})), [self.venda_a.pk])
        self.assertEqual(self.ids(cliente.get(URL, {'origem': 'analise'})), [analise.pk])
        self.assertEqual(self.ids(cliente.get(URL, {'busca': '350000000000001'})), [self.venda_a.pk])
        self.assertEqual(self.ids(cliente.get(URL, {'busca': '987654'})), [analise.pk])
        self.assertEqual(self.ids(cliente.get(URL, {'numero': self.venda_a.pk})), [self.venda_a.pk])
        self.assertEqual(self.ids(cliente.get(URL, {'cliente': 'maria'})), [self.venda_a.pk])

    def test_parametros_invalidos_viram_400_com_campos(self):
        cliente = cliente_logado(self.usuario_a)
        for params, campo in (
            ({'ordenar': 'senha'}, 'ordenar'),
            ({'data_inicio': '31/12/2026'}, 'data_inicio'),
            ({'trocadas': 'talvez'}, 'trocadas'),
            ({'numero': 'abc'}, 'numero'),
            ({'data_inicio': '2026-12-31', 'data_fim': '2026-01-01'}, 'data_fim'),
        ):
            resposta = cliente.get(URL, params)
            self.assertEqual(resposta.status_code, 400, params)
            self.assertIn(campo, resposta.json()['erro']['campos'])

    def test_ordenacao_e_periodo(self):
        outra = self.criar_venda_manual(cpf='55566677788', nome='Ana', imei='350000000000004')
        cliente = cliente_logado(self.usuario_a)
        self.assertEqual(self.ids(cliente.get(URL, {'ordenar': 'numero'})), [self.venda_a.pk, outra.pk])
        hoje = self.venda_a.data_venda.date().isoformat()
        self.assertEqual(len(self.ids(cliente.get(URL, {'data_inicio': hoje, 'data_fim': '2099-01-01'}))), 2)
        self.assertEqual(self.ids(cliente.get(URL, {'data_fim': '2000-01-01'})), [])

    def test_mutacao_pela_lista_nao_e_permitida(self):
        self.assertEqual(cliente_logado(self.usuario_a).post(URL, {}, format='json').status_code, 405)


class DetalheVendaTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_da_analise()
        self.usuario = criar_usuario('usuario', permissoes=('vendas.view_venda',), lojas=(self.loja_a,))

    def test_detalhe_completo(self):
        resposta = cliente_logado(self.usuario).get(url_venda(self.venda))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados['cliente']['cpf'], '98765432100')
        self.assertEqual(dados['origem'], 'analise')
        self.assertEqual(dados['analise_origem']['status'], 'A')
        self.assertEqual(len(dados['itens']), 1)
        self.assertEqual(dados['itens'][0]['imei'], '350000000000099')
        ipx = next(p for p in dados['pagamentos'] if p['tipo_pagamento']['nome'] == 'IPX')
        self.assertEqual(ipx['resumo']['total'], 10)
        self.assertEqual(ipx['resumo']['a_vencer'], 10)
        self.assertEqual(len(ipx['parcelas_lista']), 10)
        self.assertEqual(dados['valor_entrada'], '200.00')
        self.assertEqual({d['campo'] for d in dados['documentos']}, {'documento_assinado', 'foto_cliente', 'imagem_imei'})
        self.assertTrue(all(d['url'] is None for d in dados['documentos']))
        self.assertTrue(dados['impressos']['carne'].endswith('carne.pdf?tipo=carne'))
        self.assertFalse(dados['acoes']['cancelar'])
        self.assertEqual(dados['historico'][-1]['tipo'], 'criacao')

    def test_venda_de_outra_loja_responde_404(self):
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000005')
        resposta = cliente_logado(self.usuario).get(url_venda(outra))
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.json()['erro']['codigo'], 'nao_encontrado')

    def test_put_e_delete_nao_existem(self):
        cliente = cliente_logado(criar_usuario('admin', superuser=True))
        self.assertEqual(cliente.put(url_venda(self.venda), {}, format='json').status_code, 405)
        self.assertEqual(cliente.delete(url_venda(self.venda)).status_code, 405)
