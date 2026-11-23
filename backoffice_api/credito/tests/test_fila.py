"""Fila de solicitações, KPIs e busca global."""
from backoffice_api.credito.regras import mascarar_cpf

from .fabricas import BASE, CenarioCredito, criar_solicitacao, criar_usuario


class FilaTests(CenarioCredito):
    def test_sem_permissao_recebe_403(self):
        self.assertEqual(self.logar(self.sem_permissao).get(self.url()).status_code, 403)

    def test_usuario_da_loja_ve_so_a_propria_loja_com_cpf_mascarado(self):
        resposta = self.logar(self.analista).get(self.url())
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual([r['id'] for r in dados['results']], [self.sol_a.pk])
        item = dados['results'][0]
        self.assertEqual(item['cpf'], '***.456.789-**')
        self.assertEqual(item['status'], 'EA')
        self.assertEqual(item['status_rotulo'], 'Em análise')
        self.assertEqual(item['vendedor']['id'], self.vendedor.pk)
        self.assertEqual(item['entrada'], '200.00')
        self.assertIsNotNone(item['tempo_espera_segundos'])
        self.assertIn('page_size', dados)

    def test_administrador_global_ve_todas(self):
        dados = self.logar(self.admin).get(self.url()).json()
        self.assertEqual({r['id'] for r in dados['results']}, {self.sol_a.pk, self.sol_b.pk})

    def test_gerente_ve_lojas_gerenciadas(self):
        gerente = criar_usuario('gerente', permissoes=('vendas.view_cliente',), gerente_de=(self.loja_b,))
        dados = self.logar(gerente).get(self.url()).json()
        self.assertEqual([r['id'] for r in dados['results']], [self.sol_b.pk])

    def test_cabecalho_de_loja_fora_do_escopo_recebe_403(self):
        resposta = self.logar(self.analista).get(self.url(), HTTP_X_LOJA=str(self.loja_b.pk))
        self.assertEqual(resposta.status_code, 403)

    def test_filtros_status_busca_e_loja(self):
        criar_solicitacao(self.loja_b, self.produto, nome='Ana Reprovada', cpf='11122233344', status='R')
        cliente = self.logar(self.admin)
        self.assertEqual(cliente.get(self.url(), {'status': 'R'}).json()['count'], 1)
        self.assertEqual(cliente.get(self.url(), {'busca': '555.666'}).json()['results'][0]['id'], self.sol_b.pk)
        self.assertEqual(cliente.get(self.url(), {'loja': self.loja_a.pk}).json()['count'], 1)

    def test_filtro_invalido_recebe_400_com_campos(self):
        cliente = self.logar(self.admin)
        resposta = cliente.get(self.url(), {'status': 'X', 'data_inicio': '2026-13-01'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('status', resposta.json()['erro']['campos'])
        resposta = cliente.get(self.url(), {'ordenar': 'senha'})
        self.assertIn('ordenar', resposta.json()['erro']['campos'])

    def test_ordenacao_padrao_segue_criacao_mais_recente_primeiro(self):
        aprovada = criar_solicitacao(self.loja_a, self.produto, nome='Zeca Aprovado', cpf='22233344455', status='A')
        nova = criar_solicitacao(self.loja_a, self.produto, nome='Bia Nova', cpf='33344455566')
        ids = [r['id'] for r in self.logar(self.analista).get(self.url()).json()['results']]
        self.assertEqual(ids, [nova.pk, aprovada.pk, self.sol_a.pk])

    def test_post_na_lista_recebe_405(self):
        self.assertEqual(self.logar(self.admin).post(self.url(), {}).status_code, 405)


class KpisTests(CenarioCredito):
    def test_contadores_respeitam_escopo(self):
        criar_solicitacao(self.loja_b, self.produto, nome='Outra', cpf='99988877766', status='A')
        dados = self.logar(self.analista).get(f'{BASE}/solicitacoes/kpis/').json()
        self.assertEqual(dados['por_status'], {'EA': 1, 'A': 0, 'R': 0, 'C': 0})
        dados = self.logar(self.admin).get(f'{BASE}/solicitacoes/kpis/').json()
        self.assertEqual(dados['por_status']['A'], 1)
        self.assertEqual(dados['aprovadas_sem_venda'], 1)
        self.assertEqual(dados['total'], 3)

    def test_sem_permissao_recebe_403(self):
        self.assertEqual(self.logar(self.sem_permissao).get(f'{BASE}/solicitacoes/kpis/').status_code, 403)


class BuscaTests(CenarioCredito):
    def test_busca_por_nome_respeita_escopo(self):
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.get(f'{BASE}/busca/', {'termo': 'Pedro'}).json()['resultados'], [])
        resultados = cliente.get(f'{BASE}/busca/', {'termo': 'Maria'}).json()['resultados']
        self.assertEqual(resultados[0]['id'], self.sol_a.pk)
        self.assertEqual(resultados[0]['cpf'], '***.456.789-**')

    def test_termo_curto_devolve_vazio_e_sem_permissao_403(self):
        self.assertEqual(self.logar(self.admin).get(f'{BASE}/busca/', {'termo': 'M'}).json()['resultados'], [])
        self.assertEqual(self.logar(self.sem_permissao).get(f'{BASE}/busca/', {'termo': 'Maria'}).status_code, 403)

    def test_limita_a_oito_resultados(self):
        for i in range(10):
            criar_solicitacao(self.loja_a, self.produto, nome=f'Maria {i}', cpf=f'1000000000{i}')
        resultados = self.logar(self.admin).get(f'{BASE}/busca/', {'termo': 'Maria'}).json()['resultados']
        self.assertEqual(len(resultados), 8)

    def test_post_recebe_405(self):
        self.assertEqual(self.logar(self.admin).post(f'{BASE}/busca/', {}).status_code, 405)


class MascaraTests(CenarioCredito):
    def test_mascara(self):
        self.assertEqual(mascarar_cpf('123.456.789-01'), '***.456.789-**')
        self.assertEqual(mascarar_cpf('123'), '***')
