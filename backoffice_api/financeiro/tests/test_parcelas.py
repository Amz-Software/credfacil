"""Parcelas: edição (entrada, persistência, leitura, recarga) e inclusão de até 4."""
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.test import TestCase

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import Parcela

from .fabricas import URL_BASE, criar_conta, parcelas_de, ultima_auditoria

ANALISTA = ('ANALISTA',)
EDITAR = ('vendas.change_pagamento', 'vendas.view_pagamento')


def url_parcela(parcela):
    return f'{URL_BASE}parcelas/{parcela.pk}/'


def url_conta(conta, sufixo=''):
    return f'{URL_BASE}contas-a-receber/{conta.pk}/{sufixo}'


class EditarParcelaTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.parcela = parcelas_de(self.conta)[0]

    def _cliente(self, permissoes=EDITAR, grupos=ANALISTA):
        return cliente_logado(criar_usuario('ana', permissoes=permissoes, grupos=grupos, lojas=(self.loja,)))

    def test_edita_pagamento_persiste_e_aparece_no_detalhe(self):
        cliente = self._cliente()
        hoje = date.today()
        resposta = cliente.patch(url_parcela(self.parcela), {
            'valor_pago': '100.00', 'pago': True, 'data_pagamento': hoje.isoformat(), 'motivo': 'PIX',
        }, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()['pago'])
        self.parcela.refresh_from_db()
        self.assertEqual(self.parcela.valor_pago, Decimal('100.00'))
        self.assertEqual(self.parcela.data_pagamento, hoje)
        detalhe = cliente.get(url_conta(self.conta)).json()
        recarregada = next(p for p in detalhe['parcelas'] if p['id'] == self.parcela.pk)
        self.assertEqual(recarregada['valor_pago'], '100.00')
        self.assertTrue(recarregada['pago'])
        registro = ultima_auditoria('parcela_editada')
        self.assertEqual(registro.motivo, 'PIX')
        self.assertIn('pago', registro.dados['alteracoes'])

    def test_vencimento_exige_permissao_propria(self):
        novo = (self.parcela.data_vencimento + timedelta(days=5)).isoformat()
        resposta = self._cliente().patch(url_parcela(self.parcela), {'data_vencimento': novo}, format='json')
        self.assertEqual(resposta.status_code, 403)
        self.parcela.refresh_from_db()
        self.assertNotEqual(self.parcela.data_vencimento.isoformat(), novo)

    def test_vencimento_com_permissao(self):
        novo = self.parcela.data_vencimento + timedelta(days=5)
        cliente = self._cliente(EDITAR + ('vendas.change_vencimento_parcela',))
        resposta = cliente.patch(url_parcela(self.parcela), {'data_vencimento': novo.isoformat()}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.parcela.refresh_from_db()
        self.assertEqual(self.parcela.data_vencimento, novo)

    def test_valor_nao_e_editavel_e_valor_negativo_e_recusado(self):
        cliente = self._cliente()
        resposta = cliente.patch(url_parcela(self.parcela), {'valor': '1.00'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('valor', resposta.json()['erro']['campos'])
        resposta = cliente.patch(url_parcela(self.parcela), {'valor_pago': '-1'}, format='json')
        self.assertIn('valor_pago', resposta.json()['erro']['campos'])

    def test_sem_grupo_403_outra_loja_404_get_405(self):
        sem_grupo = self._cliente(grupos=())
        self.assertEqual(sem_grupo.patch(url_parcela(self.parcela), {'pago': True}, format='json').status_code, 403)
        cliente = cliente_logado(criar_usuario('ana2', permissoes=EDITAR, grupos=ANALISTA, lojas=(self.loja,)))
        outra = parcelas_de(criar_conta(criar_loja('B'), cpf='98765432100'))[0]
        self.assertEqual(cliente.patch(url_parcela(outra), {'pago': True}, format='json').status_code, 404)
        self.assertEqual(cliente.get(url_parcela(self.parcela)).status_code, 405)


class AdicionarParcelasTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja, valor='300.00', parcelas=3)
        Parcela.objects.filter(pagamento=self.conta, numero_parcela=1).update(pago=True, valor_pago=Decimal('100'))

    def _cliente(self, permissoes=('vendas.add_parcela', 'vendas.view_pagamento')):
        return cliente_logado(criar_usuario('ana', permissoes=permissoes, grupos=ANALISTA, lojas=(self.loja,)))

    def test_sem_permissao_recebe_403(self):
        resposta = self._cliente(('vendas.view_pagamento',)).post(
            url_conta(self.conta, 'parcelas/'), {'parcelas': [{}]}, format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_mais_de_quatro_recebe_400(self):
        resposta = self._cliente().post(url_conta(self.conta, 'parcelas/'), {'parcelas': [{}] * 5}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('parcelas', resposta.json()['erro']['campos'])

    def test_adiciona_redistribui_saldo_e_recarrega(self):
        ultima = parcelas_de(self.conta)[-1]
        data_pedida = ultima.data_vencimento + relativedelta(months=3)
        cliente = self._cliente()
        resposta = cliente.post(url_conta(self.conta, 'parcelas/'), {
            'parcelas': [{}, {'data_vencimento': data_pedida.isoformat()}], 'motivo': 'Renegociação',
        }, format='json')
        self.assertEqual(resposta.status_code, 201)
        parcelas = parcelas_de(self.conta)
        self.assertEqual([p.numero_parcela for p in parcelas], [1, 2, 3, 4, 5])
        self.assertEqual(parcelas[3].data_vencimento, ultima.data_vencimento + relativedelta(months=1))
        self.assertEqual(parcelas[4].data_vencimento, data_pedida)
        pendentes = [p for p in parcelas if not p.pago]
        self.assertEqual(sum(p.valor for p in pendentes), Decimal('200.00'))
        self.assertEqual(parcelas[1].valor, Decimal('50.00'))
        self.assertEqual(len(resposta.json()['parcelas']), 5)
        self.assertEqual(len(cliente.get(url_conta(self.conta)).json()['parcelas']), 5)
        registro = ultima_auditoria('parcelas_adicionadas')
        self.assertEqual(len(registro.dados['novas']), 2)
        self.assertEqual(registro.motivo, 'Renegociação')
