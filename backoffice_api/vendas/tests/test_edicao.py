"""PATCH da venda: itens e pagamentos nos fluxos manual e de análise, regras e auditoria."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase

from backoffice_api.models import RegistroAuditoria
from vendas.models import Pagamento, Parcela, ProdutoVenda

from .fabricas import CenarioVendas, cliente_logado, criar_usuario, url_venda


class EdicaoVendaManualTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        self.item = self.venda.itens_venda.get()
        self.pagamento = self.venda.pagamentos.get()
        self.editor = criar_usuario('editor', permissoes=('vendas.change_venda', 'vendas.view_venda'), lojas=(self.loja_a,))
        self.cliente = cliente_logado(self.editor)

    def patch(self, dados, venda=None):
        return self.cliente.patch(url_venda(venda or self.venda), dados, format='json')

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('leitor', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.patch(url_venda(self.venda), {'observacao': 'x'}, format='json').status_code, 403)

    def test_edita_itens_e_pagamentos_persiste_e_recarrega(self):
        vencimento = date.today() + timedelta(days=15)
        resposta = self.patch({
            'observacao': 'Ajuste combinado',
            'itens': [{'id': self.item.pk, 'imei': '359999999999999', 'valor_desconto': '50.00'}],
            'pagamentos': [
                {'id': self.pagamento.pk, 'parcelas': 5, 'data_primeira_parcela': vencimento.isoformat()},
                {'tipo_pagamento': self.tipo_entrada.pk, 'valor': '100.00', 'parcelas': 1,
                 'data_primeira_parcela': date.today().isoformat()},
            ],
        })
        self.assertEqual(resposta.status_code, 200, resposta.content)
        dados = resposta.json()
        self.assertEqual(dados['observacao'], 'Ajuste combinado')
        self.assertEqual(dados['itens'][0]['imei'], '359999999999999')
        self.assertEqual(dados['itens'][0]['valor_total'], '950.00')
        self.assertEqual(len(dados['pagamentos']), 2)

        self.pagamento.refresh_from_db()
        self.assertEqual(self.pagamento.parcelas, 5)
        parcelas = Parcela.objects.filter(pagamento=self.pagamento).order_by('numero_parcela')
        self.assertEqual(parcelas.count(), 5)
        self.assertEqual(parcelas.first().data_vencimento, vencimento)
        self.assertTrue(all(p.loja_id == self.loja_a.pk for p in parcelas))
        novo = Pagamento.objects.get(venda=self.venda, tipo_pagamento=self.tipo_entrada)
        self.assertEqual(novo.parcelas_pagamento.count(), 1)

        recarga = self.cliente.get(url_venda(self.venda)).json()
        self.assertEqual(recarga['itens'][0]['valor_desconto'], '50.00')
        registro = RegistroAuditoria.objects.get(acao='venda_editada')
        self.assertEqual(registro.objeto_id, str(self.venda.pk))
        self.assertIn('pagamentos', registro.dados)

    def test_mudar_so_o_desconto_do_pagamento_nao_recria_parcelas(self):
        ids_antes = set(self.pagamento.parcelas_pagamento.values_list('pk', flat=True))
        resposta = self.patch({'pagamentos': [{'id': self.pagamento.pk, 'porcentagem_desconto': '3.50'}]})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(set(self.pagamento.parcelas_pagamento.values_list('pk', flat=True)), ids_antes)

    def test_inclui_e_remove_item(self):
        resposta = self.patch({'itens': [
            {'produto': self.produto_novo.pk, 'quantidade': 1, 'valor_unitario': '300.00', 'imei': '351'},
            {'id': self.item.pk, 'remover': True},
        ]})
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(list(ProdutoVenda.objects.filter(venda=self.venda).values_list('produto_id', flat=True)),
                         [self.produto_novo.pk])

    def test_nao_deixa_a_venda_sem_itens(self):
        resposta = self.patch({'itens': [{'id': self.item.pk, 'remover': True}]})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('itens', resposta.json()['erro']['campos'])
        self.assertTrue(ProdutoVenda.objects.filter(pk=self.item.pk).exists())

    def test_validacoes_com_campos_achatados(self):
        outra = self.criar_venda_manual(cpf='11122233344', imei='350000000000007')
        casos = (
            ({'itens': [{'id': self.item.pk, 'produto': self.produto_novo.pk}]}, 'itens.0.produto'),
            ({'itens': [{'id': outra.itens_venda.get().pk, 'imei': '1'}]}, 'itens.0.id'),
            ({'itens': [{'produto': self.produto.pk}]}, 'itens.0.quantidade'),
            ({'pagamentos': [{'id': self.pagamento.pk, 'tipo_pagamento': 999999}]}, 'pagamentos.0.tipo_pagamento'),
            ({'pagamentos': [{'id': self.pagamento.pk, 'parcelas': 0}]}, 'pagamentos.0.parcelas'),
            ({'cliente': 999999}, 'cliente'),
        )
        for dados, campo in casos:
            resposta = self.patch(dados)
            self.assertEqual(resposta.status_code, 400, dados)
            self.assertIn(campo, resposta.json()['erro']['campos'], resposta.json())
        self.assertEqual(self.patch({}).status_code, 400)

    def test_pagamento_com_parcela_paga_nao_e_recriado(self):
        Parcela.objects.filter(pagamento=self.pagamento, numero_parcela=1).update(pago=True)
        resposta = self.patch({'pagamentos': [{'id': self.pagamento.pk, 'valor': '1100.00'}]})
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()['erro']['codigo'], 'regra_de_negocio')
        self.assertTrue(Parcela.objects.filter(pagamento=self.pagamento, pago=True).exists())

    def test_venda_cancelada_nao_pode_ser_editada(self):
        self.venda.is_deleted = True
        self.venda.save()
        self.assertEqual(self.patch({'observacao': 'teste'}).status_code, 422)

    def test_venda_de_outra_loja_responde_404(self):
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000008')
        self.assertEqual(self.patch({'observacao': 'x'}, venda=outra).status_code, 404)


class EdicaoVendaDaAnaliseTests(CenarioVendas, TestCase):
    """Venda gerada por análise = "finalizada": exige ANALISTA/ADMIN ou can_edit_finished_sale."""

    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_da_analise()
        self.ipx = self.venda.pagamentos.get(tipo_pagamento=self.tipo_ipx)
        self.item = self.venda.itens_venda.get()

    def dados(self):
        return {
            'itens': [{'id': self.item.pk, 'imei': '358888888888888'}],
            'pagamentos': [{'id': self.ipx.pk, 'valor': '1300.00'}],
        }

    def test_change_venda_sozinho_recebe_403(self):
        user = criar_usuario('comum', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        resposta = cliente_logado(user).patch(url_venda(self.venda), self.dados(), format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_com_permissao_de_venda_finalizada_edita_e_recarrega(self):
        user = criar_usuario('final', permissoes=('vendas.change_venda', 'vendas.can_edit_finished_sale'),
                             lojas=(self.loja_a,))
        resposta = cliente_logado(user).patch(url_venda(self.venda), self.dados(), format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        ipx = next(p for p in resposta.json()['pagamentos'] if p['id'] == self.ipx.pk)
        self.assertEqual(ipx['valor'], '1300.00')
        self.assertEqual(ipx['resumo']['total'], 10)
        self.assertEqual(ipx['valor_parcela'], '130.00')
        self.assertEqual(resposta.json()['itens'][0]['imei'], '358888888888888')

    def test_analista_edita(self):
        user = criar_usuario('analista', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        user.groups.add(Group.objects.get_or_create(name='ANALISTA')[0])
        resposta = cliente_logado(user).patch(url_venda(self.venda), {'observacao': 'ok analista'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Decimal(self.ipx.valor), self.venda.pagamentos.get(pk=self.ipx.pk).valor)
