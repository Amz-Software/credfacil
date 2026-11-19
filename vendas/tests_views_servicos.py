"""As telas do backoffice delegam às regras de vendas/services (mesmo resultado da API)."""
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from accounts.models import User
from vendas.models import Loja, Venda
from vendas.tests_services import CenarioMixin, criar_cliente


class TelasComServicosTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()
        Loja.objects.create(nome='CredFacil', credfacil=True)
        self.admin = User.objects.create_superuser(username='admin', email='a@a.com', password='x')
        self.admin.groups.add(*self.analista.groups.all())
        self.client.force_login(self.admin)
        session = self.client.session
        session['loja_id'] = self.loja.id
        session.save()

    def test_gerar_venda_pela_tela(self):
        resposta = self.client.post(reverse('vendas:gerar_venda', args=[self.cliente.pk]))

        self.assertRedirects(resposta, reverse('vendas:cliente_list'), fetch_redirect_response=False)
        venda = Venda.objects.get()
        self.assertEqual(venda.vendedor, self.admin)
        self.assertEqual(venda.pagamentos.get(tipo_pagamento__nome='IPX').valor, Decimal('1200.00'))

    def test_gerar_venda_com_pendencia_leva_para_a_edicao(self):
        self.analise.status_aplicativo = 'C'
        self.analise.save()

        resposta = self.client.post(reverse('vendas:gerar_venda', args=[self.cliente.pk]), follow=False)

        self.assertRedirects(resposta, reverse('vendas:cliente_update', args=[self.cliente.pk]),
                             fetch_redirect_response=False)
        self.assertFalse(Venda.objects.exists())

    def test_gerar_venda_por_get_volta_para_a_lista(self):
        resposta = self.client.get(reverse('vendas:gerar_venda', args=[self.cliente.pk]))
        self.assertRedirects(resposta, reverse('vendas:cliente_list'), fetch_redirect_response=False)

    def test_informar_imei_pela_tela(self):
        self.analise.imei = None
        self.analise.status_aplicativo = 'C'
        self.analise.save()

        resposta = self.client.post(reverse('vendas:informar_imei_analise', args=[self.analise.pk]),
                                    {'imei_informado': '359999999999999'})

        self.assertRedirects(resposta, reverse('vendas:cliente_list'), fetch_redirect_response=False)
        self.analise.refresh_from_db()
        self.assertEqual((self.analise.imei.imei, self.analise.status_aplicativo), ('359999999999999', 'I'))

    def test_configurar_icloud_com_digitos_invalidos_avisa(self):
        resposta = self.client.post(reverse('vendas:cliente_configurar_icloud', args=[self.cliente.pk]),
                                    {'imei_ultimos_digitos': '12'}, follow=True)

        self.assertContains(resposta, 'Informe os 4 últimos dígitos do IMEI')
        self.analise.refresh_from_db()
        self.assertFalse(self.analise.icloud_configurado_vendedor)

    def test_kpis_de_status(self):
        resposta = self.client.get(reverse('vendas:caixa_kpis'))
        self.assertEqual(resposta.json(), {'EA': 0, 'A': 1, 'R': 0, 'C': 0})

    def _consultas(self, url):
        with CaptureQueriesContext(connection) as contexto:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(contexto.captured_queries)

    def test_lista_de_lojas_nao_consulta_por_loja(self):
        url = reverse('vendas:loja_list')
        Loja.objects.create(nome='a')
        poucas = self._consultas(url)
        for i in range(5):
            Loja.objects.create(nome=f'b{i}')

        self.assertEqual(self._consultas(url), poucas)

    def test_lista_de_lojas_paginada(self):
        for i in range(25):
            Loja.objects.create(nome=f'loja {i:02d}')

        resposta = self.client.get(reverse('vendas:loja_list'))

        self.assertEqual(len(resposta.context['lojas']), 20)
        self.assertTrue(resposta.context['page_obj'].has_next())

    def test_pagina_inicial_nao_consulta_por_venda(self):
        url = reverse('vendas:index')
        Venda.objects.create(cliente=self.cliente, vendedor=self.admin, loja=self.loja, repasse_logista=0)
        poucas = self._consultas(url)
        for i in range(4):
            Venda.objects.create(cliente=criar_cliente(self.loja, f'c{i}', f'9{i}'), vendedor=self.admin,
                                 loja=self.loja, repasse_logista=0)

        self.assertEqual(self._consultas(url), poucas)
