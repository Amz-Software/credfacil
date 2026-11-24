"""API do backoffice de pagamentos online: configuração, cobranças da parcela, envio do link, registros."""
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from pagamentos_online.models import Cobranca, ConfiguracaoPagamentoOnline, RegistroPagBank
from pagamentos_online.tests.base import PagamentoOnlineTestCase, resposta_pix

URL = '/api/bo/v1/cobrancas_online/'
EDITAR = ('vendas.change_pagamento', 'vendas.view_pagamento')


class CobrancasOnlineApiTest(PagamentoOnlineTestCase):
    def cliente(self, nome='ana', grupos=('ANALISTA',), permissoes=EDITAR, lojas=None):
        usuario = criar_usuario(nome, grupos=grupos, permissoes=permissoes,
                                lojas=(self.loja,) if lojas is None else lojas)
        return cliente_logado(usuario)

    def test_analista_le_a_configuracao_mas_so_admin_altera(self):
        analista = self.cliente()
        resposta = analista.get(f'{URL}configuracao/')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()['pagbank_configurado'])
        self.assertEqual(analista.patch(f'{URL}configuracao/', {'ativo': False}, format='json').status_code, 403)
        admin = self.cliente('chefe', grupos=('ADMINISTRADOR',))
        resposta = admin.patch(f'{URL}configuracao/', {'taxa_boleto': '2.99', 'uf_padrao': 'pa'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        configuracao = ConfiguracaoPagamentoOnline.obter()
        self.assertEqual(str(configuracao.taxa_boleto), '2.99')
        self.assertEqual(configuracao.uf_padrao, 'PA')

    def test_redirecionar_exige_endereco_do_app(self):
        admin = self.cliente('chefe', grupos=('ADMINISTRADOR',))
        resposta = admin.patch(f'{URL}configuracao/', {'url_app_cliente': '', 'redirecionar_paginas_antigas': True},
                               format='json')
        self.assertEqual(resposta.status_code, 400)

    def test_parcela_mostra_opcoes_e_link_e_gera_cobranca(self):
        cliente = self.cliente()
        url = f'{URL}parcelas/{self.parcela.pk}/cobrancas/'
        dados = cliente.get(url).json()
        self.assertEqual([o['forma'] for o in dados['opcoes']], ['pix', 'boleto', 'cartao'])
        self.assertTrue(dados['link_cliente'].startswith('https://vendas.exemplo.com/pagamento/'))
        with self.pagbank((201, lambda corpo: resposta_pix(corpo['reference_id']))):
            resposta = cliente.post(url, {'forma': 'pix'}, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(resposta.json()['origem'], 'backoffice')
        self.assertEqual(Cobranca.objects.get().criado_por.username, 'ana')

    def test_parcela_de_outra_loja_nao_aparece(self):
        cliente = self.cliente(lojas=(criar_loja('Loja B'),))
        self.assertEqual(cliente.get(f'{URL}parcelas/{self.parcela.pk}/cobrancas/').status_code, 404)

    def test_enviar_link_sem_janela_do_whatsapp_explica_o_motivo(self):
        resposta = self.cliente().post(f'{URL}parcelas/{self.parcela.pk}/enviar-link/', format='json')
        self.assertEqual(resposta.status_code, 422)
        self.assertIn('24 horas', resposta.json()['erro']['mensagem'])

    def test_lista_e_registros(self):
        with self.pagbank((201, lambda corpo: resposta_pix(corpo['reference_id']))):
            self.cliente().post(f'{URL}parcelas/{self.parcela.pk}/cobrancas/', {'forma': 'pix'}, format='json')
        admin = self.cliente('chefe', grupos=('ADMINISTRADOR',))
        lista = admin.get(f'{URL}cobrancas/?status=pendente&busca=Maria').json()
        self.assertEqual(lista['count'], 1)
        self.assertEqual(admin.get(f'{URL}registros/').json()['count'], RegistroPagBank.objects.count())
        self.assertEqual(self.cliente('bia').get(f'{URL}registros/').status_code, 403)
