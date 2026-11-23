"""GET solicitacoes/{id}/opcoes-edicao/: opções dos selects do formulário de edição."""
from .fabricas import CenarioCredito


class OpcoesEdicaoTests(CenarioCredito):
    def test_analista_recebe_produtos_parcelas_vencimento_e_autenticadores(self):
        resposta = self.logar(self.analista).get(self.url(self.sol_a.pk, 'opcoes-edicao'))
        self.assertEqual(resposta.status_code, 200, resposta.content)
        dados = resposta.json()
        ids = [produto['id'] for produto in dados['produtos']]
        self.assertIn(self.produto.pk, ids)
        marca = str(self.produto.marca_id)
        self.assertEqual(dados['parcelas_por_marca'][marca], [10])
        self.assertEqual([opcao['codigo'] for opcao in dados['data_pagamento']], ['1', '10', '20'])
        self.assertEqual(dados['numeros_autenticadores'], [])

    def test_vendedor_nao_recebe_autenticadores(self):
        resposta = self.logar(self.vendedor).get(self.url(self.sol_a.pk, 'opcoes-edicao'))
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.json()['numeros_autenticadores'])

    def test_sem_permissao_403_outra_loja_404_e_post_405(self):
        url = self.url(self.sol_a.pk, 'opcoes-edicao')
        self.assertEqual(self.logar(self.sem_permissao).get(url).status_code, 403)
        self.assertEqual(self.logar(self.analista).get(self.url(self.sol_b.pk, 'opcoes-edicao')).status_code, 404)
        self.assertEqual(self.logar(self.analista).post(url, {}, format='json').status_code, 405)
