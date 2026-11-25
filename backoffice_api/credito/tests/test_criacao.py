"""POST da solicitação pelo backoffice: sempre na loja da CredFácil (IPIXX), documentos opcionais."""
from backoffice_api.tests.fabricas import criar_loja, criar_usuario
from produtos.models import Produto
from vendas.models import AnaliseCreditoCliente, Cliente

from .fabricas import PERMISSOES_ANALISTA, CenarioCredito, criar_produto, png

CRIAR = PERMISSOES_ANALISTA + ('vendas.add_cliente',)


def corpo(produto, **extra) -> dict:
    return {
        'nome': 'Joana Prado', 'cpf': '39053344705', 'telefone': '91988881111', 'nascimento': '1990-05-17',
        'endereco': 'Rua das Flores, 10', 'bairro': 'Centro', 'cidade': 'Belém', 'profissao': 'Autônoma',
        'total_renda': '2500.00', 'recebe_auxilio': False,
        'nome_adicional': 'Carlos Prado', 'contato': '91977776666', 'endereco_adicional': 'Rua B, 20',
        'produto': produto.pk, 'numero_parcelas': '10', 'data_pagamento': '10', 'analise_online': False,
        **extra,
    }


class CriacaoTests(CenarioCredito):
    def setUp(self):
        super().setUp()
        self.ipixx = criar_loja('- IPIXX')
        self.ipixx.credfacil = True
        self.ipixx.pode_vender_iphone = True  # como a IPIXX de produção: sem bloqueios, vê todos os ativos
        self.ipixx.save()
        self.criador = criar_usuario('criadora', permissoes=CRIAR + ('vendas.view_all_analise_credito',),
                                     grupos=('ANALISTA',))

    def criar(self, dados, usuario=None, formato='json'):
        return self.logar(usuario or self.criador).post(self.url(), dados, format=formato)

    def test_cria_na_loja_ipixx_sem_documentos_e_responde_o_detalhe(self):
        resposta = self.criar(corpo(self.produto))

        self.assertEqual(resposta.status_code, 201, resposta.content)
        cliente = Cliente.objects.get(cpf='39053344705')
        analise = cliente.analise_credito
        self.assertEqual((cliente.loja, analise.loja), (self.ipixx, self.ipixx))
        self.assertEqual((analise.criado_por, analise.status), (self.criador, 'EA'))
        self.assertEqual(resposta.json()['id'], cliente.pk)

    def test_ignora_loja_enviada_no_corpo(self):
        resposta = self.criar(corpo(self.produto, loja=self.loja_b.pk))

        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(Cliente.objects.get(cpf='39053344705').loja, self.ipixx)

    def test_ve_todos_os_produtos_ativos_inclusive_iphone(self):
        iphone = criar_produto(nome='iPhone 15', is_iphone=True)

        opcoes = self.logar(self.criador).get(self.url() + 'opcoes-criacao/')

        self.assertEqual(opcoes.status_code, 200, opcoes.content)
        ids = {produto['id'] for produto in opcoes.json()['produtos']}
        self.assertEqual(ids, set(Produto.objects.filter(ativo=True).values_list('pk', flat=True)))
        self.assertIn(iphone.pk, ids)
        self.assertEqual(opcoes.json()['parcelas_por_marca'][str(iphone.marca_id)], [10])
        self.assertEqual(self.criar(corpo(iphone)).status_code, 201)

    def test_documentos_opcionais_mas_gravados_quando_enviados(self):
        resposta = self.criar({**corpo(self.produto), 'foto_cliente': png()}, formato='multipart')

        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertTrue(Cliente.objects.get(cpf='39053344705').comprovantes.foto_cliente)

    def test_erros_dos_forms_viram_400_com_campos_e_nada_e_gravado(self):
        resposta = self.criar(corpo(self.produto, cpf='123'))

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('cpf', resposta.json()['erro']['campos'])
        self.assertFalse(Cliente.objects.filter(nome='Joana Prado').exists())

    def test_sem_referencia_completa_400(self):
        sem_referencia = {k: v for k, v in corpo(self.produto).items()
                          if k not in ('nome_adicional', 'contato', 'endereco_adicional')}

        resposta = self.criar(sem_referencia)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('contato', resposta.json()['erro']['campos'])

    def test_parcelamento_inexistente_400(self):
        resposta = self.criar(corpo(self.produto, numero_parcelas='7'))

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('numero_parcelas', resposta.json()['erro']['campos'])
        self.assertFalse(AnaliseCreditoCliente.objects.filter(cliente__nome='Joana Prado').exists())

    def test_vendedor_sem_grupo_de_analista_recebe_403(self):
        vendedor = criar_usuario('vend2', permissoes=('vendas.view_cliente', 'vendas.add_cliente'),
                                 grupos=('VENDEDOR',), lojas=(self.loja_a,))

        self.assertEqual(self.criar(corpo(self.produto), usuario=vendedor).status_code, 403)
        self.assertEqual(self.logar(vendedor).get(self.url() + 'opcoes-criacao/').status_code, 403)

    def test_sem_loja_ipixx_cadastrada_responde_erro_claro(self):
        self.ipixx.credfacil = False
        self.ipixx.save()

        resposta = self.criar(corpo(self.produto))

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('IPIXX', resposta.json()['erro']['mensagem'])
