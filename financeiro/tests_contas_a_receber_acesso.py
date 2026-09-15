"""Detalhes e Gerar BO em Contas a Receber são restritos a ADMINISTRADOR/ANALISTA.

As checagens de acesso permitido usam RequestFactory porque o instrumentador de
templates do test client do Django é incompatível com o Python desta venv.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from financeiro.views import (
    ContasAReceberDetailView, ContasAReceberListView, GerarNotificacaoBoView,
)
from vendas.models import (
    Cliente, ComprovantesCliente, Loja, Pagamento, Parcela, TipoPagamento, Venda,
)

PERMISSOES_BASE = ('view_pagamento', 'can_view_all_payments', 'add_notificacaobo')


def _criar_usuario(username, loja, grupo):
    user = User.objects.create_user(
        username=username, email=f'{username}@teste.com', password='x', loja=loja,
    )
    user.user_permissions.add(*Permission.objects.filter(codename__in=PERMISSOES_BASE))
    user.groups.add(Group.objects.get_or_create(name=grupo)[0])
    return user


class AcessoContasAReceberTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.vendedor = _criar_usuario('vendedor', self.loja, 'VENDEDOR')
        self.analista = _criar_usuario('analista', self.loja, 'ANALISTA')
        self.admin = _criar_usuario('admin', self.loja, 'ADMINISTRADOR')

        cliente = Cliente.objects.create(
            nome='Cliente Teste', telefone='91999999999', cpf='12345678900',
            nascimento=date(1990, 1, 1), rg='123', cep='66000000',
            endereco='Rua A', bairro='Centro', cidade='Belém',
            comprovantes=ComprovantesCliente.objects.create(),
        )
        venda = Venda.objects.create(
            cliente=cliente, vendedor=self.vendedor, loja=self.loja,
            repasse_logista=Decimal('100.00'),
        )
        tipo = TipoPagamento.objects.create(nome='IPX', parcelas=True, caixa=False)
        self.pagamento = Pagamento.objects.create(
            venda=venda, tipo_pagamento=tipo, valor=Decimal('1000.00'),
            parcelas=10, loja=self.loja, data_primeira_parcela=date.today(),
        )
        # Parcela vencida em aberto: pré-requisito do fluxo de BO
        Parcela.objects.create(
            pagamento=self.pagamento, numero_parcela=1, valor=Decimal('100.00'),
            data_vencimento=date.today() - timedelta(days=30), pago=False,
            loja=self.loja,
        )

    def _request(self, url, user):
        request = self.factory.get(url)
        request.user = user
        request.session = SessionStore()
        request.session['loja_id'] = self.loja.id
        request._messages = FallbackStorage(request)
        return request

    def _url_detalhe(self):
        return reverse('financeiro:contas_a_receber_update', args=[self.pagamento.pk])

    def _url_bo(self):
        return reverse('financeiro:notificacao_bo_preview', args=[self.pagamento.pk])

    # --- detalhes ---

    def test_analista_acessa_detalhes(self):
        response = ContasAReceberDetailView.as_view()(
            self._request(self._url_detalhe(), self.analista), pk=self.pagamento.pk
        )
        self.assertEqual(response.status_code, 200)

    def test_admin_acessa_detalhes(self):
        response = ContasAReceberDetailView.as_view()(
            self._request(self._url_detalhe(), self.admin), pk=self.pagamento.pk
        )
        self.assertEqual(response.status_code, 200)

    def test_vendedor_nao_acessa_detalhes_mesmo_com_permissao(self):
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(self._url_detalhe()).status_code, 403)

    # --- gerar BO ---

    def test_analista_acessa_gerar_bo(self):
        response = GerarNotificacaoBoView.as_view()(
            self._request(self._url_bo(), self.analista), pk=self.pagamento.pk
        )
        self.assertEqual(response.status_code, 200)

    def test_vendedor_nao_acessa_gerar_bo_mesmo_com_permissao(self):
        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(self._url_bo()).status_code, 403)

    # --- listagem: flags de ação no contexto ---

    def _contexto_listagem(self, user):
        url = reverse('financeiro:contas_a_receber_list')
        response = ContasAReceberListView.as_view()(self._request(url, user))
        self.assertEqual(response.status_code, 200)
        return response.context_data

    def test_listagem_esconde_acoes_para_vendedor(self):
        context = self._contexto_listagem(self.vendedor)
        self.assertFalse(context['pode_ver_detalhes'])
        self.assertFalse(context['pode_gerar_bo'])

    def test_listagem_mostra_acoes_para_analista(self):
        context = self._contexto_listagem(self.analista)
        self.assertTrue(context['pode_ver_detalhes'])
        self.assertTrue(context['pode_gerar_bo'])

    def test_listagem_mostra_acoes_para_admin(self):
        context = self._contexto_listagem(self.admin)
        self.assertTrue(context['pode_ver_detalhes'])
        self.assertTrue(context['pode_gerar_bo'])
