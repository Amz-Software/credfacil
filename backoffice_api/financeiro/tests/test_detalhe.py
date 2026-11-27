"""Detalhe, desconto, situações e quitação de contas a receber."""
from decimal import Decimal

from django.test import TestCase

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from vendas.models import Contato, Parcela, StatusPagamento

from .fabricas import URL_BASE, criar_conta, parcelas_de, ultima_auditoria

ANALISTA = ('ANALISTA',)


def url(pagamento, sufixo=''):
    return f'{URL_BASE}contas-a-receber/{pagamento.pk}/{sufixo}'


class DetalheTests(TestCase):
    def setUp(self):
        self.loja = criar_loja('Loja A')
        self.outra = criar_loja('Loja B')
        self.conta = criar_conta(self.loja)
        Contato.objects.create(cliente=self.conta.venda.cliente, data='2026-11-01', observacao='Mãe: 9199')

    def test_sem_grupo_analista_recebe_403(self):
        user = criar_usuario('fin', permissoes=('vendas.view_pagamento',), lojas=(self.loja,))
        self.assertEqual(cliente_logado(user).get(url(self.conta)).status_code, 403)

    def test_analista_ve_detalhe_completo(self):
        user = criar_usuario('ana', permissoes=('vendas.view_pagamento',), grupos=ANALISTA, lojas=(self.loja,))
        resposta = cliente_logado(user).get(url(self.conta))
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados['cliente']['cpf'], '12345678901')
        self.assertEqual(len(dados['parcelas']), 3)
        self.assertEqual(dados['contatos'][0]['observacao'], 'Mãe: 9199')
        self.assertEqual(len(dados['situacoes']), 10)
        self.assertEqual(dados['totais']['parcelas_totais'], 3)
        self.assertTrue(dados['pode_gerar_bo'])
        self.assertEqual(dados['estado'], 'atrasado')
        self.assertTrue(dados['historico'])

    def test_conta_de_outra_loja_e_id_inexistente_recebem_404(self):
        outra = criar_conta(self.outra, cpf='98765432100')
        user = criar_usuario('ana', permissoes=('vendas.view_pagamento',), grupos=ANALISTA, lojas=(self.loja,))
        cliente = cliente_logado(user)
        self.assertEqual(cliente.get(url(outra)).status_code, 404)
        self.assertEqual(cliente.get(f'{URL_BASE}contas-a-receber/999999/').json()['erro']['codigo'], 'nao_encontrado')

    def test_admin_global_ve_qualquer_loja(self):
        outra = criar_conta(self.outra, cpf='98765432100')
        user = criar_usuario('adm', permissoes=('vendas.view_pagamento', 'vendas.can_view_all_payments'),
                             grupos=('ADMINISTRADOR',))
        self.assertEqual(cliente_logado(user).get(url(outra)).status_code, 200)


class DescontoTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)

    def _cliente(self, *permissoes):
        return cliente_logado(criar_usuario('ana', permissoes=permissoes, grupos=ANALISTA, lojas=(self.loja,)))

    def test_sem_permissao_recebe_403(self):
        resposta = self._cliente('vendas.view_pagamento').patch(url(self.conta), {'porcentagem_desconto': '10'},
                                                                 format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_altera_desconto_sem_recriar_parcelas_e_audita(self):
        ids_antes = [p.pk for p in parcelas_de(self.conta)]
        resposta = self._cliente('vendas.change_pagamento').patch(
            url(self.conta), {'porcentagem_desconto': '12.50', 'motivo': 'Acordo com cliente'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['porcentagem_desconto'], '12.50')
        self.conta.refresh_from_db()
        self.assertEqual(self.conta.porcentagem_desconto, Decimal('12.50'))
        self.assertEqual([p.pk for p in parcelas_de(self.conta)], ids_antes)
        registro = ultima_auditoria('pagamento_desconto_alterado')
        self.assertEqual(registro.dados, {'antes': '0.00', 'depois': '12.50'})

    def test_desconto_invalido_e_campo_desconhecido_recebem_400(self):
        cliente = self._cliente('vendas.change_pagamento')
        resposta = cliente.patch(url(self.conta), {'porcentagem_desconto': '150'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('porcentagem_desconto', resposta.json()['erro']['campos'])
        resposta = cliente.patch(url(self.conta), {'porcentagem_desconto': '5', 'valor': '1'}, format='json')
        self.assertIn('valor', resposta.json()['erro']['campos'])


class SituacoesTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        user = criar_usuario('fin', permissoes=('vendas.change_pagamento',), lojas=(self.loja,))
        self.cliente = cliente_logado(user)

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('sem', lojas=(self.loja,)))
        resposta = cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'bo'}, format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_alterna_e_define_situacao_com_auditoria(self):
        ids_antes = [p.pk for p in parcelas_de(self.conta)]
        resposta = self.cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'bloqueado'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.bloqueado)
        self.assertEqual(ultima_auditoria('pagamento_situacao_alterada').dados['depois'], True)
        self.cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'bloqueado', 'ativo': True}, format='json')
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.bloqueado)
        self.cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'bloqueado', 'ativo': False}, format='json')
        self.conta.refresh_from_db()
        self.assertFalse(self.conta.bloqueado)
        self.assertEqual([p.pk for p in parcelas_de(self.conta)], ids_antes)

    def test_alterna_status_de_pagamento(self):
        status = StatusPagamento.objects.create(nome='Acordo')
        self.cliente.post(url(self.conta, 'situacoes/'), {'status_pagamento': status.pk}, format='json')
        self.assertTrue(self.conta.statuses.filter(pk=status.pk).exists())
        self.cliente.post(url(self.conta, 'situacoes/'), {'status_pagamento': status.pk}, format='json')
        self.assertFalse(self.conta.statuses.filter(pk=status.pk).exists())
        self.assertIsNotNone(ultima_auditoria('pagamento_status_alterado'))

    def test_entrada_invalida_recebe_400(self):
        resposta = self.cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'xpto'}, format='json')
        self.assertIn('situacao', resposta.json()['erro']['campos'])
        resposta = self.cliente.post(url(self.conta, 'situacoes/'), {'situacao': 'bo', 'status_pagamento': 1},
                                     format='json')
        self.assertEqual(resposta.status_code, 400)

    def test_get_recebe_405_e_outra_loja_404(self):
        self.assertEqual(self.cliente.get(url(self.conta, 'situacoes/')).status_code, 405)
        outra = criar_conta(criar_loja('Loja B'), cpf='98765432100')
        resposta = self.cliente.post(url(outra, 'situacoes/'), {'situacao': 'bo'}, format='json')
        self.assertEqual(resposta.status_code, 404)


class QuitacaoTests(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.conta.porcentagem_desconto = Decimal('10')
        self.conta.save(update_fields=['porcentagem_desconto'])
        user = criar_usuario('ana', permissoes=('vendas.can_confirm_quitacao',), lojas=(self.loja,))
        self.cliente = cliente_logado(user)

    def test_sem_permissao_recebe_403(self):
        cliente = cliente_logado(criar_usuario('sem', lojas=(self.loja,)))
        self.assertEqual(cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Cliente pagou'}, format='json')
                         .status_code, 403)

    def test_motivo_obrigatorio(self):
        resposta = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'ok'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('motivo', resposta.json()['erro']['campos'])

    def test_sem_parcela_aguardando_recebe_422(self):
        resposta = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Cliente pagou'}, format='json')
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()['erro']['codigo'], 'regra_de_negocio')

    def test_quita_com_desconto_e_audita(self):
        Parcela.objects.filter(pagamento=self.conta, numero_parcela__in=[2, 3]).update(pagamento_efetuado=True)
        resposta = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Quitação antecipada'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        parcelas = parcelas_de(self.conta)
        self.assertFalse(parcelas[0].pago)
        self.assertTrue(parcelas[1].pago and parcelas[2].pago)
        self.assertEqual(parcelas[1].valor + parcelas[2].valor, Decimal('180.00'))
        self.conta.refresh_from_db()
        self.assertTrue(self.conta.quitado)
        registro = ultima_auditoria('pagamento_quitado')
        self.assertEqual(registro.motivo, 'Quitação antecipada')
        self.assertEqual(registro.dados['parcelas_quitadas'], 2)

    def test_repetir_depois_de_quitada_devolve_o_detalhe_sem_erro_nem_nova_auditoria(self):
        # Caso de produção: a 1ª resposta não chega à tela (timeout) e o usuário clica de novo.
        Parcela.objects.filter(pagamento=self.conta, numero_parcela=3).update(pagamento_efetuado=True)
        primeira = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Cliente pagou'}, format='json')
        self.assertEqual(primeira.status_code, 200)

        repetida = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Cliente pagou'}, format='json')

        self.assertEqual(repetida.status_code, 200)
        self.assertTrue(repetida.json()['quitado'])
        self.assertEqual(parcelas_de(self.conta)[2].valor, Decimal('90.00'))
        self.assertEqual(RegistroAuditoria.objects.filter(acao='pagamento_quitado').count(), 1)

    def test_forcar_sem_ser_administrador_recebe_403(self):
        resposta = self.cliente.post(url(self.conta, 'quitar/'), {'motivo': 'Cliente pagou', 'forcar': True},
                                     format='json')
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(any(p.pago for p in parcelas_de(self.conta)))

    def test_administrador_quita_sem_informe_do_cliente_todas_as_parcelas_em_aberto(self):
        Parcela.objects.filter(pagamento=self.conta, numero_parcela=1).update(pago=True)
        admin = criar_usuario('adm', permissoes=('vendas.can_confirm_quitacao',), grupos=('ADMINISTRADOR',),
                              lojas=(self.loja,))

        resposta = cliente_logado(admin).post(
            url(self.conta, 'quitar/'), {'motivo': 'Pagou na loja', 'forcar': True}, format='json')

        self.assertEqual(resposta.status_code, 200)
        parcelas = parcelas_de(self.conta)
        self.assertTrue(all(p.pago for p in parcelas))
        self.assertEqual(parcelas[1].valor + parcelas[2].valor, Decimal('180.00'))
        registro = ultima_auditoria('pagamento_quitado')
        self.assertTrue(registro.dados['sem_informe_do_cliente'])
        self.assertEqual(registro.dados['parcelas_quitadas'], 2)

    def test_forcar_sem_parcela_em_aberto_recebe_422(self):
        Parcela.objects.filter(pagamento=self.conta).update(pago=True)
        admin = criar_usuario('adm', permissoes=('vendas.can_confirm_quitacao',), grupos=('ADMINISTRADOR',),
                              lojas=(self.loja,))
        resposta = cliente_logado(admin).post(
            url(self.conta, 'quitar/'), {'motivo': 'Pagou na loja', 'forcar': True}, format='json')
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()['erro']['mensagem'], 'Nenhuma parcela em aberto para quitar.')

    def test_get_recebe_405(self):
        self.assertEqual(self.cliente.get(url(self.conta, 'quitar/')).status_code, 405)
