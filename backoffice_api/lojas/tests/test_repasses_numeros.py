"""Repasses (lista, criação, status, agenda) e números autenticadores."""
import itertools
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.test import TestCase

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from financeiro.models import Repasse
from vendas.models import NumeroAutenticador

from .fabricas import URL_BASE, criar_repasse, criar_venda, ids, ultima_auditoria

URL_REPASSES = f'{URL_BASE}repasses/'
URL_NUMEROS = f'{URL_BASE}numeros-autenticadores/'
_sequencia = itertools.count(1)


class RepassesTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Alfa')
        self.loja_b = criar_loja('Beta')
        self.dono = criar_usuario('dono')
        self.rep_a = criar_repasse(self.loja_a, date.today() - timedelta(days=10), self.dono)
        self.rep_b = criar_repasse(self.loja_b, date.today() - timedelta(days=5), self.dono, status='pago')

    def _cliente(self, *permissoes, lojas=None):
        return cliente_logado(criar_usuario(f'fin{next(_sequencia)}', permissoes=permissoes, lojas=lojas or (self.loja_a,)))

    def test_lista_permissao_escopo_e_filtros(self):
        self.assertEqual(self._cliente().get(URL_REPASSES).status_code, 403)
        cliente = self._cliente('financeiro.view_repasse')
        self.assertEqual(ids(cliente.get(URL_REPASSES)), [self.rep_a.pk])
        self.assertEqual(cliente.get(URL_REPASSES, {'loja': self.loja_b.pk}).status_code, 404)
        global_ = cliente_logado(criar_usuario('glob', permissoes=('financeiro.view_repasse',
                                                                     'vendas.can_view_all_stores')))
        self.assertEqual(ids(global_.get(URL_REPASSES, {'status': 'pago'})), [self.rep_b.pk])
        self.assertEqual(global_.get(URL_REPASSES, {'status': 'xpto'}).status_code, 400)
        periodo = global_.get(URL_REPASSES, {'data_inicio': (date.today() - timedelta(days=6)).isoformat()})
        self.assertEqual(ids(periodo), [self.rep_b.pk])
        linha = cliente.get(URL_REPASSES).json()['results'][0]
        self.assertEqual(linha['data'], (date.today() - timedelta(days=10)).isoformat())

    def test_criar_no_escopo_e_audita(self):
        self.assertEqual(self._cliente('financeiro.view_repasse').post(URL_REPASSES, {}, format='json').status_code,
                         403)
        cliente = self._cliente('financeiro.add_repasse')
        fora = cliente.post(URL_REPASSES, {'loja': self.loja_b.pk, 'valor': '10', 'data': '2026-11-06'},
                            format='json')
        self.assertIn('loja', fora.json()['erro']['campos'])
        invalido = cliente.post(URL_REPASSES, {'loja': self.loja_a.pk, 'valor': '0', 'data': '2026-11-06'},
                                format='json')
        self.assertIn('valor', invalido.json()['erro']['campos'])
        resposta = cliente.post(URL_REPASSES, {'loja': self.loja_a.pk, 'valor': '250.00', 'data': '2026-11-06',
                                               'observacao': 'Quinzena'}, format='json')
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['data'], '2026-11-06')
        self.assertEqual(resposta.json()['status'], 'pendente')
        self.assertIsNotNone(ultima_auditoria('repasse_criado'))

    def test_transicoes_de_status(self):
        cliente = self._cliente('financeiro.change_repasse')
        url = f'{URL_REPASSES}{self.rep_a.pk}/'
        resposta = cliente.patch(url, {'status': 'pago', 'motivo': 'TED enviada'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.rep_a.refresh_from_db()
        self.assertEqual(self.rep_a.status, 'pago')
        registro = ultima_auditoria('repasse_status_alterado')
        self.assertEqual((registro.dados['antes'], registro.dados['depois'], registro.motivo),
                         ('pendente', 'pago', 'TED enviada'))
        self.assertEqual(cliente.patch(url, {'status': 'pendente'}, format='json').status_code, 422)
        self.assertEqual(cliente.patch(url, {'valor': '1.00'}, format='json').status_code, 422)
        self.assertEqual(cliente.patch(url, {'observacao': 'Comprovante no e-mail'}, format='json').status_code, 200)
        self.assertEqual(cliente.patch(f'{URL_REPASSES}{self.rep_b.pk}/', {'status': 'cancelado'},
                                       format='json').status_code, 404)
        self.assertEqual(cliente.get(url).status_code, 405)

    def test_agendados_por_loja(self):
        mes_anterior = date.today().replace(day=1) - relativedelta(months=1)
        criar_venda(self.loja_a, mes_anterior.replace(day=10))
        self.assertEqual(self._cliente().get(f'{URL_REPASSES}agendados/').status_code, 403)
        cliente = self._cliente('financeiro.view_repasse')
        dados = cliente.get(f'{URL_REPASSES}agendados/').json()
        self.assertEqual([item['loja']['id'] for item in dados['results']], [self.loja_a.pk])
        agenda = dados['results'][0]
        self.assertEqual(agenda['total_atrasados'], 1)
        self.assertEqual(agenda['atrasados'][0]['data'], mes_anterior.replace(day=16).isoformat())
        self.assertEqual(cliente.get(f'{URL_REPASSES}agendados/', {'loja': self.loja_b.pk}).status_code, 404)


class NumerosAutenticadoresTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Alfa')
        self.loja_b = criar_loja('Beta')
        self.num_a = NumeroAutenticador.objects.create(numero='(91) 99999-0000', loja=self.loja_a)
        self.num_b = NumeroAutenticador.objects.create(numero='(91) 98888-0000', loja=self.loja_b)

    def _analista(self):
        return cliente_logado(criar_usuario('ana', grupos=('ANALISTA',), lojas=(self.loja_a,)))

    def test_grupo_obrigatorio_e_escopo(self):
        vendedor = cliente_logado(criar_usuario('vend', grupos=('VENDEDOR',), lojas=(self.loja_a,)))
        self.assertEqual(vendedor.get(URL_NUMEROS).status_code, 403)
        cliente = self._analista()
        self.assertEqual(ids(cliente.get(URL_NUMEROS)), [self.num_a.pk])
        self.assertEqual(cliente.get(f'{URL_NUMEROS}{self.num_b.pk}/').status_code, 404)
        admin = cliente_logado(criar_usuario('adm', grupos=('ADMINISTRADOR',),
                                             permissoes=('vendas.can_view_all_stores',)))
        self.assertEqual(len(ids(admin.get(URL_NUMEROS))), 2)

    def test_criar_editar_e_excluir_auditado(self):
        cliente = self._analista()
        invalido = cliente.post(URL_NUMEROS, {'numero': '123'}, format='json')
        self.assertIn('numero', invalido.json()['erro']['campos'])
        fora = cliente.post(URL_NUMEROS, {'numero': '91977776666', 'loja_id': self.loja_b.pk}, format='json')
        self.assertIn('loja_id', fora.json()['erro']['campos'])
        criado = cliente.post(URL_NUMEROS, {'numero': '(91) 97777-6666', 'descricao': 'WhatsApp'}, format='json')
        self.assertEqual(criado.status_code, 201)
        self.assertEqual(criado.json()['loja']['id'], self.loja_a.pk)
        url = f'{URL_NUMEROS}{criado.json()["id"]}/'
        self.assertFalse(cliente.patch(url, {'ativo': False}, format='json').json()['ativo'])
        self.assertEqual(cliente.delete(url).status_code, 204)
        self.assertFalse(NumeroAutenticador.objects.filter(pk=criado.json()['id']).exists())
        self.assertEqual(ultima_auditoria('numero_autenticador_removido').dados['numero'], '(91) 97777-6666')
        self.assertFalse(Repasse.objects.exists())
