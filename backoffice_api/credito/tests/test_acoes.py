"""Ações do analista sobre a solicitação."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from estoque.models import EstoqueImei
from backoffice_api.models import RegistroAuditoria
from vendas.models import ConsultaSerasaAcesso, Loja, ObservacaoSolicitacao, Pagamento, Venda

from .fabricas import CenarioCredito, criar_produto, criar_solicitacao, criar_tipos_pagamento


class DecisoesTests(CenarioCredito):
    def test_aprovar_audita_e_responde_item(self):
        resposta = self.logar(self.analista).post(self.url(self.sol_a.pk, 'aprovar'))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['solicitacao']['status'], 'A')
        registro = RegistroAuditoria.objects.get(acao='analise_aprovada')
        self.assertEqual(registro.dados['status_anterior'], 'EA')
        self.assertEqual(registro.usuario, self.analista)

    def test_vendedor_nao_aprova(self):
        self.assertEqual(self.logar(self.vendedor).post(self.url(self.sol_a.pk, 'aprovar')).status_code, 403)
        self.sol_a.analise_credito.refresh_from_db()
        self.assertEqual(self.sol_a.analise_credito.status, 'EA')

    def test_outra_loja_404_e_get_405(self):
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.post(self.url(self.sol_b.pk, 'aprovar')).status_code, 404)
        self.assertEqual(cliente.get(self.url(self.sol_a.pk, 'aprovar')).status_code, 405)

    def test_aprovar_duas_vezes_422(self):
        cliente = self.logar(self.analista)
        cliente.post(self.url(self.sol_a.pk, 'aprovar'))
        resposta = cliente.post(self.url(self.sol_a.pk, 'aprovar'))
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()['erro']['codigo'], 'regra_de_negocio')

    def test_reprovar_exige_motivo(self):
        cliente = self.logar(self.analista)
        resposta = cliente.post(self.url(self.sol_a.pk, 'reprovar'), {'motivo': 'ab'}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('motivo', resposta.json()['erro']['campos'])
        resposta = cliente.post(self.url(self.sol_a.pk, 'reprovar'), {'motivo': 'Renda insuficiente'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        registro = RegistroAuditoria.objects.get(acao='analise_reprovada')
        self.assertEqual(registro.motivo, 'Renda insuficiente')
        self.assertEqual(registro.dados['status_novo'], 'R')
        self.assertTrue(ObservacaoSolicitacao.objects.filter(texto__contains='Renda insuficiente').exists())

    def test_cancelar_exige_as_duas_permissoes_e_motivo(self):
        sem_change = self.logar(self.vendedor)
        self.assertEqual(
            sem_change.post(self.url(self.sol_a.pk, 'cancelar'), {'motivo': 'Desistiu'}, format='json').status_code, 403,
        )
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.post(self.url(self.sol_a.pk, 'cancelar'), {}, format='json').status_code, 400)
        resposta = cliente.post(self.url(self.sol_a.pk, 'cancelar'), {'motivo': 'Cliente desistiu'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(RegistroAuditoria.objects.get(acao='analise_cancelada').motivo, 'Cliente desistiu')


class ObservacoesTests(CenarioCredito):
    def test_analista_adiciona(self):
        resposta = self.logar(self.analista).post(self.url(self.sol_a.pk, 'observacoes'), {'texto': 'Ok'}, format='json')
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['autor']['id'], self.analista.pk)
        self.assertTrue(RegistroAuditoria.objects.filter(acao='observacao_adicionada').exists())

    def test_vendedor_nao_adiciona_e_texto_vazio_400(self):
        url = self.url(self.sol_a.pk, 'observacoes')
        self.assertEqual(self.logar(self.vendedor).post(url, {'texto': 'Oi'}, format='json').status_code, 403)
        resposta = self.logar(self.analista).post(url, {'texto': '   '}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('texto', resposta.json()['erro']['campos'])


class AplicativoTests(CenarioCredito):
    def test_status_app(self):
        url = self.url(self.sol_a.pk, 'status-app')
        cliente = self.logar(self.vendedor)
        self.assertEqual(cliente.post(url, {'status_app': 'X'}, format='json').status_code, 400)
        resposta = cliente.post(url, {'status_app': 'C'}, format='json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['solicitacao']['status_app'], 'C')
        self.assertTrue(RegistroAuditoria.objects.filter(acao='status_app_alterado').exists())
        self.assertEqual(self.logar(self.sem_permissao).post(url, {'status_app': 'P'}, format='json').status_code, 403)

    def test_instalar_app(self):
        resposta = self.logar(self.vendedor).post(self.url(self.sol_a.pk, 'instalar-app'))
        self.assertEqual(resposta.json()['solicitacao']['status_app'], 'C')
        self.assertEqual(self.logar(self.vendedor).post(self.url(self.sol_b.pk, 'instalar-app')).status_code, 404)

    def test_informar_imei_e_confirmar_instalacao(self):
        analise = self.sol_a.analise_credito
        analise.status_aplicativo = 'C'
        analise.save()
        cliente = self.logar(self.analista)
        self.assertEqual(cliente.post(self.url(self.sol_a.pk, 'informar-imei'), {}, format='json').status_code, 400)
        resposta = cliente.post(self.url(self.sol_a.pk, 'informar-imei'), {'imei': '350000000000009'}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertTrue(EstoqueImei.objects.filter(imei='350000000000009', loja=self.loja_a).exists())
        self.assertEqual(resposta.json()['solicitacao']['status_app'], 'I')
        self.assertTrue(RegistroAuditoria.objects.filter(acao='imei_informado').exists())

    def test_informar_imei_exige_grupo_analista(self):
        resposta = self.logar(self.admin).post(self.url(self.sol_a.pk, 'informar-imei'), {'imei': '1'}, format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_confirmar_instalacao_sem_imei_422(self):
        analise = self.sol_a.analise_credito
        analise.status_aplicativo = 'C'
        analise.save()
        resposta = self.logar(self.analista).post(self.url(self.sol_a.pk, 'confirmar-instalacao'))
        self.assertEqual(resposta.status_code, 422)

    def test_confirmar_icloud(self):
        iphone = criar_produto(nome='iPhone', is_iphone=True)
        sol = criar_solicitacao(self.loja_a, iphone, nome='Cris', cpf='44455566677', icloud_configurado_vendedor=True)
        resposta = self.logar(self.analista).post(self.url(sol.pk, 'confirmar-icloud'))
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()['solicitacao']['icloud_confirmado_analista'])
        self.assertEqual(self.logar(self.vendedor).post(self.url(sol.pk, 'confirmar-icloud')).status_code, 403)


class GerarVendaTests(CenarioCredito):
    def preparar(self):
        criar_tipos_pagamento()
        Loja.objects.filter(pk=self.loja_a.pk).update(credfacil=True)
        imei = EstoqueImei.objects.create(produto=self.produto, imei='350000000000001', loja=self.loja_a)
        analise = self.sol_a.analise_credito
        analise.status, analise.status_aplicativo, analise.imei = 'A', 'I', imei
        analise.save()

    def test_gera_venda_com_o_mesmo_calculo_do_servico(self):
        self.preparar()
        resposta = self.logar(self.analista).post(self.url(self.sol_a.pk, 'gerar-venda'))
        self.assertEqual(resposta.status_code, 201, resposta.content)
        venda = Venda.objects.get(pk=resposta.json()['venda_id'])
        ipx = Pagamento.objects.get(venda=venda, tipo_pagamento__nome='IPX')
        self.assertEqual(str(ipx.valor), '1200.00')
        self.assertEqual(ipx.parcelas, 10)
        self.assertEqual(str(ipx.porcentagem_desconto), '5.00')
        self.assertTrue(resposta.json()['solicitacao']['venda_gerada'])
        self.assertEqual(RegistroAuditoria.objects.get(acao='venda_gerada').objeto_id, str(venda.pk))

    def test_nao_aprovada_422_e_sem_permissao_403(self):
        criar_tipos_pagamento()
        Loja.objects.filter(pk=self.loja_a.pk).update(credfacil=True)
        self.assertEqual(self.logar(self.analista).post(self.url(self.sol_a.pk, 'gerar-venda')).status_code, 422)
        self.assertEqual(self.logar(self.vendedor).post(self.url(self.sol_a.pk, 'gerar-venda')).status_code, 403)


class LogSerasaTests(CenarioCredito):
    def test_registra_acesso(self):
        url = self.url(self.sol_a.pk, 'log-consulta-serasa')
        resposta = self.logar(self.analista).post(url, {'tipo': 'serasa_2'}, format='json')
        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(ConsultaSerasaAcesso.objects.filter(tipo='serasa_2', usuario=self.analista).exists())
        self.assertTrue(RegistroAuditoria.objects.filter(acao='consulta_serasa_aberta').exists())

    def test_tipo_invalido_400_e_vendedor_403(self):
        url = self.url(self.sol_a.pk, 'log-consulta-serasa')
        self.assertEqual(self.logar(self.analista).post(url, {'tipo': 'x'}, format='json').status_code, 400)
        self.assertEqual(self.logar(self.vendedor).post(url, {'tipo': 'serasa'}, format='json').status_code, 403)


class NotificarVendedorTests(CenarioCredito):
    def liberar_venda(self):
        imei = EstoqueImei.objects.create(produto=self.produto, imei='350000000000009', loja=self.loja_a)
        analise = self.sol_a.analise_credito
        analise.status, analise.status_aplicativo, analise.imei = 'A', 'I', imei
        analise.save()

    def test_notifica_o_vendedor_com_o_popup_de_venda_liberada(self):
        self.liberar_venda()
        antes = self.vendedor.notifications.unread().count()
        with mock.patch('notificacao.avisos_vendedor.enviar_ws_para_usuario') as ws:
            resposta = self.logar(self.analista).post(self.url(self.sol_a.pk, 'notificar-vendedor'))
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.json()['aguardar_segundos'], 30)
        self.assertEqual(ws.call_args.kwargs['event'], 'venda_liberada')
        self.assertEqual(ws.call_args.kwargs['usuario'], self.vendedor)
        self.assertEqual(ws.call_args.kwargs['target_url'], f'/app/solicitacoes/{self.sol_a.pk}')
        self.assertEqual(self.vendedor.notifications.unread().count(), antes + 1)
        registro = RegistroAuditoria.objects.get(acao='vendedor_notificado')
        self.assertEqual(registro.dados['vendedor_id'], self.vendedor.pk)

    def test_segundo_clique_antes_de_30s_429_e_depois_libera(self):
        self.liberar_venda()
        cliente = self.logar(self.analista)
        url = self.url(self.sol_a.pk, 'notificar-vendedor')
        with mock.patch('notificacao.avisos_vendedor.enviar_ws_para_usuario'):
            self.assertEqual(cliente.post(url).status_code, 200)
            repetido = cliente.post(url)
            self.assertEqual(repetido.status_code, 429)
            self.assertEqual(repetido.json()['erro']['codigo'], 'limite_excedido')
            RegistroAuditoria.objects.filter(acao='vendedor_notificado').update(
                criado_em=timezone.now() - timedelta(seconds=31),
            )
            self.assertEqual(cliente.post(url).status_code, 200)
        self.assertEqual(RegistroAuditoria.objects.filter(acao='vendedor_notificado').count(), 2)

    def test_venda_nao_liberada_422_e_vendedor_403(self):
        url = self.url(self.sol_a.pk, 'notificar-vendedor')
        self.assertEqual(self.logar(self.analista).post(url).status_code, 422)
        self.assertEqual(self.logar(self.vendedor).post(url).status_code, 403)
        self.assertFalse(RegistroAuditoria.objects.filter(acao='vendedor_notificado').exists())

    def test_detalhe_mostra_botao_e_ultimo_aviso(self):
        cliente = self.logar(self.analista)
        detalhe = cliente.get(self.url(self.sol_a.pk)).json()
        self.assertFalse(detalhe['acoes']['notificar_vendedor'])
        self.assertIsNone(detalhe['vendedor_notificado_em'])
        self.liberar_venda()
        with mock.patch('notificacao.avisos_vendedor.enviar_ws_para_usuario'):
            cliente.post(self.url(self.sol_a.pk, 'notificar-vendedor'))
        detalhe = cliente.get(self.url(self.sol_a.pk)).json()
        self.assertTrue(detalhe['acoes']['notificar_vendedor'])
        self.assertIsNotNone(detalhe['vendedor_notificado_em'])
