"""Testes da ação de exclusão em massa por loja no admin.

A ação é chamada diretamente (RequestFactory) em vez de via `self.client`:
neste ambiente o test client quebra ao renderizar qualquer página do admin
(incompatibilidade Django 4.2 + Python 3.14 em `Context.__copy__`).
"""

from datetime import date
from decimal import Decimal

from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.template.response import TemplateResponse
from django.test import RequestFactory, TestCase

from vendas.admin_actions import CAMPO_CONFIRMACAO, excluir_em_massa
from vendas.models import Cliente, ComprovantesCliente, Loja, Venda

User = get_user_model()


class ExclusaoEmMassaAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='senha-forte-123'
        )
        self.loja_alvo = Loja.objects.create(nome='Loja Alvo')
        self.loja_preservada = Loja.objects.create(nome='Loja Preservada')

    def _criar_cliente(self, nome, loja):
        return Cliente.objects.create(
            nome=nome,
            telefone='91999999999',
            cpf='12345678901',
            nascimento=date(1990, 1, 1),
            rg='1234567',
            cep='66000000',
            endereco='Rua A',
            bairro='Centro',
            cidade='Belém',
            loja=loja,
            comprovantes=ComprovantesCliente.objects.create(loja=loja),
        )

    def _criar_venda(self, cliente):
        return Venda.objects.create(
            cliente=cliente,
            vendedor=self.admin,
            repasse_logista=Decimal('10.00'),
            loja=cliente.loja,
        )

    def _executar(self, modelo, queryset, confirmar):
        dados = {'action': 'excluir_em_massa', 'index': '0', 'select_across': '0'}
        if confirmar:
            dados[CAMPO_CONFIRMACAO] = '1'
        request = self.factory.post('/admin/', dados)
        request.user = self.admin
        request.session = {}
        request._messages = FallbackStorage(request)
        modeladmin = django_admin.site._registry[modelo]
        return excluir_em_massa(modeladmin, request, queryset)

    def test_sem_confirmacao_apenas_mostra_a_previa(self):
        cliente = self._criar_cliente('Maria', self.loja_alvo)

        resposta = self._executar(
            Cliente, Cliente.objects.filter(pk=cliente.pk), confirmar=False
        )

        self.assertIsInstance(resposta, TemplateResponse)
        self.assertEqual(resposta.context_data['total'], 1)
        self.assertEqual(resposta.context_data['lojas'], ['Loja Alvo'])
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())

    def test_previa_lista_os_modelos_removidos_em_cascata(self):
        cliente = self._criar_cliente('Maria', self.loja_alvo)
        self._criar_venda(cliente)

        resposta = self._executar(
            Cliente, Cliente.objects.filter(pk=cliente.pk), confirmar=False
        )

        modelos = dict(resposta.context_data['contagens'])
        self.assertEqual(modelos['Clientes'], 1)
        self.assertEqual(modelos['Vendas'], 1)

    def test_exclui_apenas_os_clientes_da_loja_selecionada(self):
        alvo = self._criar_cliente('Maria', self.loja_alvo)
        self._criar_venda(alvo)
        preservado = self._criar_cliente('João', self.loja_preservada)
        self._criar_venda(preservado)

        self._executar(
            Cliente, Cliente.objects.filter(loja=self.loja_alvo), confirmar=True
        )

        self.assertFalse(Cliente.objects.filter(pk=alvo.pk).exists())
        self.assertFalse(Venda.objects.filter(cliente_id=alvo.pk).exists())
        self.assertTrue(Cliente.objects.filter(pk=preservado.pk).exists())
        self.assertEqual(Venda.objects.filter(cliente=preservado).count(), 1)

    def test_exclui_vendas_da_loja_sem_remover_o_cliente(self):
        cliente = self._criar_cliente('Maria', self.loja_alvo)
        venda = self._criar_venda(cliente)

        self._executar(Venda, Venda.objects.filter(loja=self.loja_alvo), confirmar=True)

        self.assertFalse(Venda.objects.filter(pk=venda.pk).exists())
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())

    def test_exclui_selecao_maior_que_um_lote(self):
        from vendas.admin_actions import TAMANHO_LOTE

        total = TAMANHO_LOTE + 3
        for indice in range(total):
            self._criar_cliente(f'Cliente {indice}', self.loja_alvo)

        self._executar(
            Cliente, Cliente.objects.filter(loja=self.loja_alvo), confirmar=True
        )

        self.assertEqual(Cliente.objects.filter(loja=self.loja_alvo).count(), 0)

    def test_acao_exige_permissao_de_exclusao(self):
        self.assertEqual(list(excluir_em_massa.allowed_permissions), ['delete'])

    def test_selecao_vazia_nao_quebra(self):
        resposta = self._executar(Cliente, Cliente.objects.none(), confirmar=True)

        self.assertIsNone(resposta)
