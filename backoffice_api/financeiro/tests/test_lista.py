"""Lista de contas a receber: permissão, escopo de loja, filtros e N+1."""
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import Parcela, StatusPagamento

from .fabricas import URL_BASE, criar_conta, ids, parcelas_de, tipo_entrada

URL = f'{URL_BASE}contas-a-receber/'
VER = ('vendas.view_pagamento',)


class ListaPermissaoEscopoTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Loja A')
        self.loja_b = criar_loja('Loja B')
        self.conta_a = criar_conta(self.loja_a, nome='Ana A')
        self.conta_b = criar_conta(self.loja_b, nome='Bruno B', cpf='98765432100')

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('sem', lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL).status_code, 403)

    def test_usuario_da_loja_ve_so_a_propria_loja(self):
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        resposta = cliente.get(URL)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(ids(resposta), [self.conta_a.pk])

    def test_usuario_pedindo_outra_loja_no_cabecalho_recebe_403(self):
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(cliente.get(URL, HTTP_X_LOJA=str(self.loja_b.pk)).status_code, 403)

    def test_gerente_ve_a_loja_gerenciada(self):
        cliente = cliente_logado(criar_usuario('gerente', permissoes=VER, gerente_de=(self.loja_b,)))
        self.assertEqual(ids(cliente.get(URL)), [self.conta_b.pk])

    def test_permissao_global_de_pagamentos_ve_todas(self):
        user = criar_usuario('global', permissoes=VER + ('vendas.can_view_all_payments',))
        resposta = cliente_logado(user).get(URL, HTTP_X_LOJA='todas')
        self.assertEqual(sorted(ids(resposta)), sorted([self.conta_a.pk, self.conta_b.pk]))

    def test_cpf_mascarado_na_lista(self):
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        linha = cliente.get(URL).json()['results'][0]
        self.assertEqual(linha['cliente']['cpf'], '***.456.789-**')
        self.assertNotIn('12345678901', str(linha))

    def test_post_na_lista_recebe_405(self):
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(cliente.post(URL, {}, format='json').status_code, 405)

    def test_lista_ignora_entrada_e_venda_cancelada(self):
        entrada = criar_conta(self.loja_a, parcelas=1, tipo=tipo_entrada())
        cancelada = criar_conta(self.loja_a)
        cancelada.venda.is_deleted = True
        cancelada.venda.save()
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        resultado = ids(cliente.get(URL))
        self.assertNotIn(entrada.pk, resultado)
        self.assertNotIn(cancelada.pk, resultado)


class ListaFiltrosTests(TestCase):
    def setUp(self):
        self.loja = criar_loja('Loja A')
        self.outra = criar_loja('Loja B')
        hoje = date.today()
        self.atrasada = criar_conta(self.loja, nome='Carla Atrasada', cpf='11122233344')
        self.em_dia = criar_conta(self.loja, nome='Daniel Em Dia', cpf='55566677788', primeira=hoje + timedelta(days=5))
        self.quitada = criar_conta(self.loja, nome='Eva Quitada', cpf='99988877766', parcelas=1)
        Parcela.objects.filter(pagamento=self.quitada).update(pago=True, data_pagamento=hoje - timedelta(days=50))
        self.cliente = cliente_logado(criar_usuario('fin', permissoes=VER, lojas=(self.loja,)))

    def test_status_atrasado_quitado_pendente_e_no_prazo(self):
        self.assertEqual(ids(self.cliente.get(URL, {'status': 'atrasado'})), [self.atrasada.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'status': 'quitado'})), [self.quitada.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'status': 'pendente'})), [self.em_dia.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'status': 'no_prazo'})), [self.quitada.pk])

    def test_status_invalido_recebe_400_com_campo(self):
        resposta = self.cliente.get(URL, {'status': 'xpto'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('status', resposta.json()['erro']['campos'])

    def test_busca_por_nome_cpf_e_numero(self):
        self.assertEqual(ids(self.cliente.get(URL, {'busca': 'carla'})), [self.atrasada.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'busca': '555.666'})), [self.em_dia.pk])
        self.assertIn(self.quitada.pk, ids(self.cliente.get(URL, {'busca': str(self.quitada.pk)})))

    def test_situacoes_combinadas(self):
        self.atrasada.bloqueado = True
        self.atrasada.save(update_fields=['bloqueado'])
        Parcela.objects.filter(pagamento=self.em_dia, numero_parcela=1).update(pagamento_efetuado=True)
        self.assertEqual(ids(self.cliente.get(URL, {'situacao': 'bloqueado'})), [self.atrasada.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'situacao': 'pagamento_efetuado'})), [self.em_dia.pk])
        self.assertEqual(ids(self.cliente.get(URL, {'situacao': ['bloqueado', 'pagamento_efetuado']})), [])
        self.assertEqual(self.cliente.get(URL, {'situacao': 'nada'}).status_code, 400)

    def test_status_pagamento_multiplo(self):
        status = StatusPagamento.objects.create(nome='Acordo')
        self.em_dia.statuses.add(status)
        self.assertEqual(ids(self.cliente.get(URL, {'status_pagamento': [status.pk]})), [self.em_dia.pk])

    def test_filtro_de_loja_exige_ver_todas_as_lojas(self):
        self.assertEqual(self.cliente.get(URL, {'loja': self.loja.pk}).status_code, 403)
        admin = criar_usuario('admin', permissoes=VER + ('vendas.can_view_all_stores',))
        conta_outra = criar_conta(self.outra, cpf='00011122233')
        resposta = cliente_logado(admin).get(URL, {'loja': self.outra.pk})
        self.assertEqual(ids(resposta), [conta_outra.pk])

    def test_ordenacao_por_lista_branca(self):
        resposta = self.cliente.get(URL, {'ordenar': 'cliente'})
        nomes = [linha['cliente']['nome'] for linha in resposta.json()['results']]
        self.assertEqual(nomes, sorted(nomes))
        self.assertEqual(self.cliente.get(URL, {'ordenar': 'senha'}).status_code, 400)

    def test_valores_da_linha(self):
        linha = next(r for r in self.cliente.get(URL).json()['results'] if r['id'] == self.atrasada.pk)
        vencidas = [p for p in parcelas_de(self.atrasada) if p.data_vencimento < date.today()]
        self.assertEqual(linha['estado'], 'atrasado')
        self.assertEqual(linha['valores']['valor_atrasado'], f'{Decimal("100.00") * len(vencidas):.2f}')
        self.assertEqual(linha['valores']['ultimo_vencimento_atrasado'], vencidas[-1].data_vencimento.isoformat())
        self.assertEqual(linha['valores']['parcelas_totais'], 3)
        self.assertEqual(linha['valores']['situacao_parcela_aberta'], 'atrasado')
        self.assertEqual(linha['valor'], '300.00')

    def test_sem_n_mais_1(self):
        with CaptureQueriesContext(connection) as poucas:
            self.cliente.get(URL)
        for numero in range(5):
            criar_conta(self.loja, nome=f'Extra {numero}', cpf=f'4445556660{numero}', valor=str(Decimal('100')))
        with CaptureQueriesContext(connection) as muitas:
            self.cliente.get(URL)
        self.assertEqual(len(poucas), len(muitas))
