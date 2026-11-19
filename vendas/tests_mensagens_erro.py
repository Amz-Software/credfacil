"""Falhas inesperadas viram mensagem amigável; o detalhe técnico vai só para o log."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import User
from vendas.models import Pagamento, TipoPagamento, Venda
from vendas.tests_services import CenarioMixin

SEGREDO = 'detalhe-interno-do-banco'


class MensagensDeErroTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.admin = User.objects.create_superuser(username='admin', email='a@a.com', password='x')
        self.client.force_login(self.admin)
        session = self.client.session
        session['loja_id'] = self.loja.id
        session.save()
        self.venda = Venda.objects.create(cliente=self.cliente, vendedor=self.admin, loja=self.loja,
                                          repasse_logista=0)

    def test_confirmar_quitacao_nao_mostra_a_excecao(self):
        pagamento = Pagamento.objects.create(
            venda=self.venda, tipo_pagamento=TipoPagamento.objects.get(nome='IPX'), valor=Decimal('100'),
            parcelas=1, loja=self.loja, data_primeira_parcela=date.today(),
        )
        with mock.patch('django.db.transaction.atomic', side_effect=RuntimeError(SEGREDO)), \
                self.assertLogs('vendas', level='ERROR'):
            resposta = self.client.post(reverse('vendas:confirmar_quitacao', args=[pagamento.pk]))

        mensagens = [str(m) for m in resposta.wsgi_request._messages]
        self.assertTrue(any('Não foi possível confirmar a quitação' in m for m in mensagens))
        self.assertFalse(any(SEGREDO in m for m in mensagens))

    def test_api_trocar_produto_inexistente_responde_sem_excecao(self):
        api = APIClient()
        api.force_authenticate(self.admin)

        resposta = api.post(reverse('venda-trocar-produto', args=[self.venda.pk]),
                            {'produto_atual': 999, 'novo_produto': 999, 'imei': self.imei.pk}, format='json')

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(resposta.data['detail'], 'Produto da venda ou novo produto não encontrado.')
