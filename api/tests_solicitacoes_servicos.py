"""Endpoints de solicitação/loja usam as mesmas regras de vendas/services que as telas."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import User
from vendas.models import Loja, Venda
from vendas.tests_services import CenarioMixin


class SolicitacaoServicosApiTests(CenarioMixin, APITestCase):
    def setUp(self):
        self.montar_cenario()
        Loja.objects.create(nome='CredFacil', credfacil=True)
        self.admin = User.objects.create_superuser(username='admin', email='a@a.com', password='x')
        self.admin.groups.add(*self.analista.groups.all())
        self.client.force_authenticate(self.admin)

    def _post(self, acao, dados=None):
        return self.client.post(reverse(f'solicitacao-{acao}', args=[self.cliente.pk]), dados or {}, format='json')

    def test_gerar_venda(self):
        resposta = self._post('gerar-venda')

        self.assertEqual(resposta.status_code, 201, resposta.data)
        venda = Venda.objects.get(pk=resposta.data['id'])
        self.assertEqual(venda.repasse_logista, Decimal('1000.00'))
        self.assertEqual(venda.pagamentos.get(tipo_pagamento__nome='IPX').parcelas_pagamento.count(), 10)

    def test_gerar_venda_sem_app_instalado_responde_400(self):
        self.analise.status_aplicativo = 'C'
        self.analise.save()

        resposta = self._post('gerar-venda')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('Aplicativo não está instalado', resposta.data['detail'])

    def test_informar_imei_exige_analista(self):
        self.client.force_authenticate(self.vendedor)
        self.vendedor.is_superuser = True
        self.vendedor.save()

        resposta = self._post('informar-imei-analise', {'imei_informado': '1'})

        self.assertEqual(resposta.status_code, 403)

    def test_informar_imei_libera_a_venda(self):
        self.analise.imei = None
        self.analise.status_aplicativo = 'C'
        self.analise.save()

        resposta = self._post('informar-imei-analise', {'imei_informado': '358888888888888'})

        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.analise.refresh_from_db()
        self.assertEqual((self.analise.imei_informado, self.analise.status_aplicativo), ('358888888888888', 'I'))

    def test_cancelar_desfaz_a_venda(self):
        venda_id = self._post('gerar-venda').data['id']

        resposta = self._post('cancelar')

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(Venda.objects.get(pk=venda_id).is_deleted)

    def test_configurar_icloud_valida_digitos(self):
        self.assertEqual(self._post('configurar-icloud', {'imei_ultimos_digitos': '1'}).status_code, 400)
        self.assertEqual(self._post('configurar-icloud', {'imei_ultimos_digitos': '1234'}).status_code, 200)

    def test_kpis(self):
        resposta = self.client.get(reverse('solicitacao-kpis'))
        self.assertEqual(resposta.data['kpis'], {'EA': 0, 'A': 1, 'R': 0, 'C': 0})

    def test_lista_de_lojas_nao_consulta_repasses_por_loja(self):
        def consultas():
            with CaptureQueriesContext(connection) as contexto:
                self.assertEqual(self.client.get(reverse('loja-list')).status_code, 200)
            tabelas = ('"vendas_venda"', '"financeiro_repasse"')
            return [q['sql'] for q in contexto.captured_queries if any(t in q['sql'] for t in tabelas)]

        poucas = consultas()
        for i in range(4):
            Loja.objects.create(nome=f'extra {i}')

        self.assertEqual(len(consultas()), len(poucas))

    def test_replicar_qrcode_sem_origem_responde_400(self):
        resposta = self.client.post(reverse('loja-replicar-qrcode', args=[self.loja.pk]))
        self.assertEqual(resposta.status_code, 400)
