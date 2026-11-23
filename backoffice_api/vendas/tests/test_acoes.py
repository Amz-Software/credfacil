"""Edição especial, troca de produto, IMEIs disponíveis e cancelamento."""
from django.test import TestCase

from backoffice_api.models import RegistroAuditoria
from estoque.models import Estoque, EstoqueImei
from vendas.models import Parcela, Venda

from .fabricas import URL, CenarioVendas, cliente_logado, criar_usuario, url_venda


class EdicaoEspecialTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_da_analise()
        self.item = self.venda.itens_venda.get()
        self.ipx = self.venda.pagamentos.get(tipo_pagamento=self.tipo_ipx)
        self.entrada = self.venda.pagamentos.get(tipo_pagamento=self.tipo_entrada)
        user = criar_usuario('especial', permissoes=('vendas.can_edit_imei_valores_venda',), lojas=(self.loja_a,))
        self.cliente = cliente_logado(user)
        self.url = url_venda(self.venda, 'edicao-especial/')

    def test_sem_permissao_recebe_403(self):
        user = criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        resposta = cliente_logado(user).post(self.url, {'motivo': 'Ajuste de IMEI', 'itens': []}, format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_motivo_obrigatorio(self):
        resposta = self.cliente.post(self.url, {'itens': [{'id': self.item.pk, 'imei': '1'}]}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('motivo', resposta.json()['erro']['campos'])
        resposta = self.cliente.post(self.url, {'motivo': 'abc', 'itens': [{'id': self.item.pk}]}, format='json')
        self.assertIn('motivo', resposta.json()['erro']['campos'])

    def test_altera_imei_produto_e_parcelas_sem_mexer_nos_valores(self):
        valor_antes = self.ipx.valor
        resposta = self.cliente.post(self.url, {
            'motivo': 'Cliente pediu outro aparelho',
            'itens': [{'id': self.item.pk, 'produto': self.produto_novo.pk, 'imei': '357777777777777'}],
            'pagamentos': [{'id': self.ipx.pk, 'parcelas': 12}],
        }, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.item.refresh_from_db()
        self.ipx.refresh_from_db()
        self.assertEqual((self.item.produto_id, self.item.imei), (self.produto_novo.pk, '357777777777777'))
        self.assertEqual((self.ipx.parcelas, self.ipx.valor), (12, valor_antes))
        self.assertEqual(Parcela.objects.filter(pagamento=self.ipx).count(), 12)
        registro = RegistroAuditoria.objects.get(acao='venda_edicao_especial')
        self.assertEqual(registro.motivo, 'Cliente pediu outro aparelho')
        self.assertEqual(registro.dados['pagamentos'][0]['parcelas'], [10, 12])

    def test_parcelas_fora_da_lista_e_entrada_viram_400(self):
        resposta = self.cliente.post(self.url, {'motivo': 'Ajuste geral', 'pagamentos': [{'id': self.ipx.pk, 'parcelas': 7}]},
                                     format='json')
        self.assertIn('pagamentos.0.parcelas', resposta.json()['erro']['campos'])
        resposta = self.cliente.post(self.url, {'motivo': 'Ajuste geral', 'pagamentos': [{'id': self.entrada.pk, 'parcelas': 4}]},
                                     format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('pagamentos.0.parcelas', resposta.json()['erro']['campos'])

    def test_venda_de_outra_loja_responde_404(self):
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000010')
        resposta = self.cliente.post(url_venda(outra, 'edicao-especial/'),
                                     {'motivo': 'Ajuste geral', 'itens': [{'id': 1, 'imei': '2'}]}, format='json')
        self.assertEqual(resposta.status_code, 404)

    def test_get_nao_e_permitido(self):
        self.assertEqual(self.cliente.get(self.url).status_code, 405)


class TrocaProdutoTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        self.item = self.venda.itens_venda.get()
        self.imei_novo = EstoqueImei.objects.create(produto=self.produto_novo, imei='356666666666666', loja=self.loja_a)
        Estoque.objects.create(produto=self.produto_novo, loja=self.loja_a, quantidade_disponivel=3)
        self.user = criar_usuario('trocador', permissoes=('vendas.change_venda',), lojas=(self.loja_a,))
        self.cliente = cliente_logado(self.user)
        self.url = url_venda(self.venda, 'trocar-produto/')

    def dados(self, **extra):
        return {'produto_atual': self.item.pk, 'novo_produto': self.produto_novo.pk, 'imei': self.imei_novo.pk,
                'motivo': 'Defeito de fábrica', **extra}

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('leitor', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.post(self.url, self.dados(), format='json').status_code, 403)

    def test_troca_marca_venda_registra_observacao_e_audita(self):
        resposta = self.cliente.post(self.url, self.dados(), format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.json()['situacao'], 'trocada')
        self.venda.refresh_from_db()
        self.item.refresh_from_db()
        self.assertTrue(self.venda.is_trocado)
        self.assertEqual((self.item.produto_id, self.item.imei), (self.produto_novo.pk, '356666666666666'))
        self.assertIn('Motivo: Defeito de fábrica', self.venda.observacao)
        registro = RegistroAuditoria.objects.get(acao='venda_produto_trocado')
        self.assertEqual(registro.motivo, 'Defeito de fábrica')

    def test_validacoes(self):
        self.assertIn('motivo', self.cliente.post(self.url, self.dados(motivo=''), format='json').json()['erro']['campos'])
        imei_errado = EstoqueImei.objects.create(produto=self.produto, imei='355555555555555', loja=self.loja_a)
        resposta = self.cliente.post(self.url, self.dados(imei=imei_errado.pk), format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('imei', resposta.json()['erro']['campos'])
        imei_outra_loja = EstoqueImei.objects.create(produto=self.produto_novo, imei='354444444444444', loja=self.loja_b)
        resposta = self.cliente.post(self.url, self.dados(imei=imei_outra_loja.pk), format='json')
        self.assertIn('imei', resposta.json()['erro']['campos'])
        resposta = self.cliente.post(self.url, self.dados(produto_atual=999999), format='json')
        self.assertIn('produto_atual', resposta.json()['erro']['campos'])

    def test_opcoes_de_troca(self):
        resposta = self.cliente.get(url_venda(self.venda, 'opcoes-troca/'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([p['id'] for p in resposta.json()['produtos_disponiveis']], [self.produto_novo.pk])
        self.assertEqual(resposta.json()['itens'][0]['id'], self.item.pk)


class ImeisDisponiveisTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()  # usa o IMEI 350000000000001
        EstoqueImei.objects.create(produto=self.produto, imei='350000000000001', loja=self.loja_a)
        self.livre = EstoqueImei.objects.create(produto=self.produto, imei='350000000000020', loja=self.loja_a)
        EstoqueImei.objects.create(produto=self.produto, imei='350000000000021', loja=self.loja_b)
        EstoqueImei.objects.create(produto=self.produto, imei='350000000000022', loja=self.loja_a, vendido=True)
        self.url = f'{URL}imeis-disponiveis/'

    def test_lista_so_livres_do_escopo(self):
        cliente = cliente_logado(criar_usuario('troca', permissoes=('vendas.change_venda',), lojas=(self.loja_a,)))
        resposta = cliente.get(self.url, {'produto': self.produto.pk})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([i['id'] for i in resposta.json()['results']], [self.livre.pk])
        self.assertEqual(cliente.get(self.url).status_code, 400)

    def test_quem_ve_todos_os_imeis_ve_outras_lojas(self):
        user = criar_usuario('todos', permissoes=('vendas.change_venda', 'estoque.can_view_all_imei'), lojas=(self.loja_a,))
        resposta = cliente_logado(user).get(self.url, {'produto': self.produto.pk})
        self.assertEqual(resposta.json()['count'], 2)
        resposta = cliente_logado(user).get(self.url, {'produto': self.produto.pk, 'venda': self.venda.pk})
        self.assertEqual(resposta.json()['count'], 1)

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('leitor', permissoes=('vendas.view_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(self.url, {'produto': self.produto.pk}).status_code, 403)


class CancelamentoTests(CenarioVendas, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.venda = self.criar_venda_manual()
        self.url = url_venda(self.venda, 'cancelar/')
        self.cliente = cliente_logado(criar_usuario('cancelador', permissoes=('vendas.delete_venda',), lojas=(self.loja_a,)))

    def test_change_venda_nao_basta(self):
        cliente = cliente_logado(criar_usuario('editor', permissoes=('vendas.change_venda',), lojas=(self.loja_a,)))
        self.assertEqual(cliente.post(self.url, {'motivo': 'Desistência'}, format='json').status_code, 403)

    def test_cancela_com_motivo_e_audita(self):
        self.assertEqual(self.cliente.post(self.url, {}, format='json').status_code, 400)
        resposta = self.cliente.post(self.url, {'motivo': 'Cliente desistiu'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['situacao'], 'cancelada')
        self.assertTrue(Venda.objects.get(pk=self.venda.pk).is_deleted)
        self.assertEqual(RegistroAuditoria.objects.get(acao='venda_cancelada').motivo, 'Cliente desistiu')
        segunda = self.cliente.post(self.url, {'motivo': 'De novo'}, format='json')
        self.assertEqual(segunda.status_code, 422)

    def test_get_nao_cancela(self):
        self.assertEqual(self.cliente.get(self.url).status_code, 405)
        self.assertFalse(Venda.objects.get(pk=self.venda.pk).is_deleted)

    def test_outra_loja_responde_404(self):
        outra = self.criar_venda_manual(self.loja_b, cpf='11122233344', imei='350000000000011')
        resposta = self.cliente.post(url_venda(outra, 'cancelar/'), {'motivo': 'Cliente desistiu'}, format='json')
        self.assertEqual(resposta.status_code, 404)
