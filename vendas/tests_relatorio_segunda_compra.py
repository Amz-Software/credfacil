"""Coluna '2ª Compra' no relatório de vendas reflete PreAnaliseRapida.segunda_compra."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase

from accounts.models import User
from vendas.models import (
    Cliente, ComprovantesCliente, Loja, PreAnaliseRapida, Venda,
)
from vendas.views import FolhaRelatorioVendasView


def _cliente(nome):
    return Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf='12345678900',
        nascimento=date(1990, 1, 1), rg='123', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém',
        comprovantes=ComprovantesCliente.objects.create(),
    )


class RelatorioVendasSegundaCompraTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.loja = Loja.objects.create(nome='Loja Teste')
        self.user = User.objects.create_user(
            username='gestor', email='gestor@teste.com', password='x', loja=self.loja,
        )
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_generate_report_sale'),
        )

        self.cliente_recorrente = _cliente('Cliente Recorrente')
        self.cliente_novo = _cliente('Cliente Novo')

        self.venda_recorrente = Venda.objects.create(
            cliente=self.cliente_recorrente, vendedor=self.user, loja=self.loja,
            repasse_logista=Decimal('100.00'),
        )
        self.venda_nova = Venda.objects.create(
            cliente=self.cliente_novo, vendedor=self.user, loja=self.loja,
            repasse_logista=Decimal('100.00'),
        )

        PreAnaliseRapida.objects.create(
            nome_completo='Cliente Recorrente', cpf='12345678900', loja=self.loja,
            criado_por=self.user, cliente_gerado=self.cliente_recorrente,
            segunda_compra=True,
        )
        PreAnaliseRapida.objects.create(
            nome_completo='Cliente Novo', cpf='12345678900', loja=self.loja,
            criado_por=self.user, cliente_gerado=self.cliente_novo,
            segunda_compra=False,
        )

    def _vendas_do_relatorio(self):
        request = self.factory.get('/vendas/relatorio/folha/')
        request.user = self.user
        request.session = SessionStore()
        request.session['loja_id'] = self.loja.id
        request._messages = FallbackStorage(request)
        response = FolhaRelatorioVendasView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        return {v.pk: v for v in response.context_data['vendas']}

    def test_venda_de_cliente_recorrente_marca_segunda_compra(self):
        vendas = self._vendas_do_relatorio()
        self.assertTrue(vendas[self.venda_recorrente.pk].is_segunda_compra)

    def test_venda_de_cliente_novo_nao_marca_segunda_compra(self):
        vendas = self._vendas_do_relatorio()
        self.assertFalse(vendas[self.venda_nova.pk].is_segunda_compra)

    def test_venda_sem_pre_analise_nao_marca_segunda_compra(self):
        venda_avulsa = Venda.objects.create(
            cliente=_cliente('Cliente Avulso'), vendedor=self.user, loja=self.loja,
            repasse_logista=Decimal('50.00'),
        )
        vendas = self._vendas_do_relatorio()
        self.assertFalse(vendas[venda_avulsa.pk].is_segunda_compra)
