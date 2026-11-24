"""Ações de um período do calendário de repasses: marcar como pago e PDF."""
import itertools
from datetime import date
from decimal import Decimal
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.test import TestCase

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from financeiro.models import Repasse

from .fabricas import URL_BASE, criar_repasse, criar_venda, ultima_auditoria

URL_PAGAR = f'{URL_BASE}repasses/pagar-periodo/'
URL_PDF = f'{URL_BASE}repasses/periodo-pdf/'
_sequencia = itertools.count(1)


def _mes_anterior() -> date:
    return date.today().replace(day=1) - relativedelta(months=1)


class PagarPeriodoTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Alfa')
        self.loja_b = criar_loja('Beta')
        mes = _mes_anterior()
        self.dia = mes.replace(day=16)
        criar_venda(self.loja_a, mes.replace(day=7), repasse='300.00')
        criar_venda(self.loja_a, mes.replace(day=15), repasse='450.50')
        criar_venda(self.loja_a, mes.replace(day=20), repasse='999.00')  # outro período

    def _cliente(self, *permissoes, lojas=None):
        usuario = criar_usuario(f'fin{next(_sequencia)}', permissoes=permissoes, lojas=lojas or (self.loja_a,))
        return cliente_logado(usuario)

    def _pagar(self, cliente, loja=None, dia=None):
        dados = {'loja': (loja or self.loja_a).pk, 'data': (dia or self.dia).isoformat()}
        return cliente.post(URL_PAGAR, dados, format='json')

    def test_cria_repasse_pago_com_total_do_periodo_e_audita(self):
        resposta = self._pagar(self._cliente('financeiro.add_repasse'))

        self.assertEqual(resposta.status_code, 201)
        corpo = resposta.json()
        self.assertEqual((corpo['status'], corpo['valor'], corpo['data']), ('pago', '750.50', self.dia.isoformat()))
        repasse = Repasse.objects.get(pk=corpo['id'])
        self.assertEqual(repasse.valor, Decimal('750.50'))
        self.assertIsNotNone(ultima_auditoria('repasse_periodo_pago'))

    def test_exige_permissao_de_criar_repasse(self):
        self.assertEqual(self._pagar(self._cliente('financeiro.view_repasse')).status_code, 403)

    def test_loja_fora_do_escopo(self):
        resposta = self._pagar(self._cliente('financeiro.add_repasse'), loja=self.loja_b)
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(Repasse.objects.filter(loja=self.loja_b).exists())

    def test_recusa_periodo_ja_lancado(self):
        criar_repasse(self.loja_a, self.dia, criar_usuario('dono'))
        resposta = self._pagar(self._cliente('financeiro.add_repasse'))
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(Repasse.objects.filter(loja=self.loja_a).count(), 1)

    def test_recusa_data_fora_do_calendario(self):
        resposta = self._pagar(self._cliente('financeiro.add_repasse'), dia=self.dia.replace(day=15))
        self.assertEqual(resposta.status_code, 422)

    def test_recusa_periodo_sem_vendas(self):
        resposta = self._pagar(self._cliente('financeiro.add_repasse'), dia=self.dia.replace(day=6))
        self.assertEqual(resposta.status_code, 422)

    def test_paga_periodo_em_andamento_com_total_atual(self):
        proximo = date.today().replace(day=1) + relativedelta(months=1)
        criar_venda(self.loja_a, date.today(), repasse='120.00')
        dia = next(d for d in (
            date.today().replace(day=6), date.today().replace(day=16), date.today().replace(day=26),
            proximo.replace(day=6),
        ) if d > date.today())
        resposta = self._pagar(self._cliente('financeiro.add_repasse'), dia=dia)
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['valor'], '120.00')

    def test_recusa_periodo_futuro_sem_vendas(self):
        futuro = (date.today().replace(day=1) + relativedelta(months=2)).replace(day=16)
        resposta = self._pagar(self._cliente('financeiro.add_repasse'), dia=futuro)
        self.assertEqual(resposta.status_code, 422)


class PdfDoPeriodoTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Alfa')
        self.loja_b = criar_loja('Beta')
        mes = _mes_anterior()
        self.dia = mes.replace(day=16)
        criar_venda(self.loja_a, mes.replace(day=7), repasse='300.00')

    def _cliente(self, *permissoes):
        usuario = criar_usuario(f'pdf{next(_sequencia)}', permissoes=permissoes, lojas=(self.loja_a,))
        return cliente_logado(usuario)

    def _parametros(self, loja=None, dia=None) -> dict:
        return {'loja': (loja or self.loja_a).pk, 'data': (dia or self.dia).isoformat()}

    @mock.patch('backoffice_api.lojas.pdf_repasse.gerar_pdf', return_value=b'%PDF-falso')
    def test_devolve_pdf_com_vendas_do_periodo(self, gerar_pdf):
        resposta = self._cliente('financeiro.view_repasse').get(URL_PDF, self._parametros())

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertIn('repasse_', resposta['Content-Disposition'])
        html = gerar_pdf.call_args.args[0]
        self.assertIn('Alfa', html)
        self.assertIn('300,00', html)

    def test_exige_permissao_e_escopo(self):
        self.assertEqual(self._cliente().get(URL_PDF, self._parametros()).status_code, 403)
        cliente = self._cliente('financeiro.view_repasse')
        self.assertEqual(cliente.get(URL_PDF, self._parametros(loja=self.loja_b)).status_code, 404)

    def test_valida_data_do_calendario(self):
        cliente = self._cliente('financeiro.view_repasse')
        self.assertEqual(cliente.get(URL_PDF, self._parametros(dia=self.dia.replace(day=15))).status_code, 422)
        self.assertEqual(cliente.get(URL_PDF, {'loja': self.loja_a.pk, 'data': 'xx'}).status_code, 400)
