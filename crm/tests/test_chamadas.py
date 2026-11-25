"""Ligações pelo WhatsApp: webhook da Meta, atendimento, ligação feita, permissão e telas."""
import json
import os
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from crm.models import Chamada, ConfiguracaoCRM, Conversa, Mensagem, TentativaContato
from crm.services import chamadas
from crm.tests.base import CrmTestCase
from crm.webhook import processar_payload
from crm.whatsapp_chamadas import ChamadasSimuladas

TELEFONE = '5591999990000'
SDP = 'v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\ns=-\r\n'
JSON = 'application/json'


def _calls(*eventos, statuses=(), numero=''):
    valor = {'calls': list(eventos), 'statuses': list(statuses)}
    if numero:
        valor['metadata'] = {'phone_number_id': numero}
    return {'entry': [{'changes': [{'field': 'calls', 'value': valor}]}]}


def conexao_recebida(call_id='wacid.1'):
    return {'id': call_id, 'from': TELEFONE, 'event': 'connect', 'direction': 'USER_INITIATED',
            'session': {'sdp_type': 'offer', 'sdp': SDP}}


def fim(call_id='wacid.1', duracao=None, status='COMPLETED'):
    evento = {'id': call_id, 'event': 'terminate', 'status': status}
    if duracao:
        evento.update(duration=duracao, start_time='1767000000', end_time=str(1767000000 + duracao))
    return evento


class ChamadaRecebidaTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        ConfiguracaoCRM.objects.filter(pk=1).update(chamadas_ativas=True)

    def test_toca_a_primeira_pessoa_atende_e_a_conversa_registra_a_duracao(self):
        processar_payload(_calls(conexao_recebida()))
        chamada = Chamada.objects.get()
        self.assertEqual((chamada.status, chamada.direcao), (Chamada.Status.TOCANDO, Chamada.Direcao.ENTRADA))

        atendeu = self.web(self.atendente).post(f'/crm/chamadas/{chamada.pk}/atender/', json.dumps({'sdp': SDP}),
                                                content_type=JSON)
        tarde = self.web(self.outro).post(f'/crm/chamadas/{chamada.pk}/atender/', json.dumps({'sdp': SDP}),
                                          content_type=JSON)
        processar_payload(_calls(fim(duracao=125)))

        self.assertEqual(atendeu.status_code, 200)
        self.assertEqual((tarde.status_code, tarde.json()['motivo']), (409, 'JA_ATENDIDA'))
        chamada.refresh_from_db()
        self.assertEqual((chamada.status, chamada.usuario, chamada.duracao_s),
                         (Chamada.Status.ENCERRADA, self.atendente, 125))
        registro = Mensagem.objects.get(tipo=Mensagem.Tipo.CHAMADA)
        self.assertIn('Ligação recebida · 2 min 05 s', registro.texto)
        self.assertEqual(registro.autor, Mensagem.Autor.SISTEMA)
        self.assertEqual(chamada.conversa.assumida_por, self.atendente)

    def test_ninguem_atendeu_vira_nao_atendida(self):
        processar_payload(_calls(conexao_recebida()))
        processar_payload(_calls(fim()))

        self.assertEqual(Chamada.objects.get().status, Chamada.Status.PERDIDA)
        self.assertIn('não atendida', Mensagem.objects.get(tipo=Mensagem.Tipo.CHAMADA).texto)

    def test_sdp_invalido_e_toque_vencido_nao_atendem(self):
        processar_payload(_calls(conexao_recebida()))
        chamada = Chamada.objects.get()
        web = self.web(self.atendente)

        invalido = web.post(f'/crm/chamadas/{chamada.pk}/atender/', json.dumps({'sdp': 'lixo'}), content_type=JSON)
        Chamada.objects.filter(pk=chamada.pk).update(iniciada_em=timezone.now() - timedelta(minutes=5))
        vencido = web.post(f'/crm/chamadas/{chamada.pk}/atender/', json.dumps({'sdp': SDP}), content_type=JSON)

        self.assertEqual(invalido.status_code, 409)
        self.assertEqual((vencido.status_code, vencido.json()['motivo']), (409, 'EXPIRADA'))

    def test_rotina_fecha_toque_esquecido_e_lista_o_que_esta_tocando(self):
        processar_payload(_calls(conexao_recebida()))
        tocando = self.web(self.atendente).get('/crm/chamadas/tocando/').json()['chamadas']
        Chamada.objects.update(iniciada_em=timezone.now() - timedelta(minutes=5))

        self.assertEqual(len(tocando), 1)
        self.assertEqual(tocando[0]['sdp_oferta'], SDP)
        self.assertEqual(chamadas.fechar_esquecidas(), 1)
        self.assertEqual(Chamada.objects.get().status, Chamada.Status.PERDIDA)

    def test_evento_de_outro_numero_da_empresa_e_ignorado(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_PHONE_NUMBER_ID': '111'}):
            processar_payload(_calls(conexao_recebida('wacid.outro'), numero='999'))
            processar_payload(_calls(conexao_recebida('wacid.nosso'), numero='111'))

        self.assertEqual(list(Chamada.objects.values_list('wa_call_id', flat=True)), ['wacid.nosso'])


class ChamadaFeitaTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        ConfiguracaoCRM.objects.filter(pk=1).update(chamadas_ativas=True)

    def _ligar(self, conversa, usuario=None):
        return self.web(usuario or self.atendente).post(f'/crm/conversas/{conversa.pk}/ligar/',
                                                         json.dumps({'sdp': SDP}), content_type=JSON)

    def test_precisa_assumir_e_ter_permissao_do_cliente(self):
        conversa = self.receber('Oi').conversa
        sem_dono = self._ligar(conversa)
        conversa = self.conversa_com_humano()
        with mock.patch.object(ChamadasSimuladas, 'permissao_padrao', 'no_permission'):
            sem_permissao = self._ligar(conversa)

        self.assertEqual(sem_dono.json()['motivo'], 'NAO_ASSUMIDA')
        self.assertEqual((sem_permissao.status_code, sem_permissao.json()['motivo']), (409, 'SEM_PERMISSAO'))
        self.assertFalse(Chamada.objects.exists())

    def test_cliente_atende_e_vira_tentativa_de_contato(self):
        from crm.tests.test_pagamentos import CPF_VALIDO, NASCIMENTO
        from vendas.models import Cliente, ComprovantesCliente, Loja

        loja = Loja.objects.create(nome='Loja')
        cliente = Cliente.objects.create(nome='Maria', telefone='91999990000', cpf=CPF_VALIDO, nascimento=NASCIMENTO,
                                         rg='1', cep='66000000', endereco='Rua', bairro='B', cidade='Belém',
                                         loja=loja, comprovantes=ComprovantesCliente.objects.create(loja=loja))
        conversa = self.conversa_com_humano()
        conversa.clientes.add(cliente)

        resposta = self._ligar(conversa)
        chamada = Chamada.objects.get()
        processar_payload(_calls({'id': chamada.wa_call_id, 'event': 'connect', 'direction': 'BUSINESS_INITIATED',
                                  'session': {'sdp_type': 'answer', 'sdp': SDP}},
                                 statuses=[{'id': chamada.wa_call_id, 'type': 'call', 'status': 'ACCEPTED'}]))
        detalhe = self.web(self.atendente).get(f'/crm/chamadas/{chamada.pk}/').json()
        processar_payload(_calls(fim(chamada.wa_call_id, duracao=40)))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual((detalhe['sdp_resposta'], detalhe['status']), (SDP, Chamada.Status.EM_ANDAMENTO))
        chamada.refresh_from_db()
        self.assertEqual(chamada.status, Chamada.Status.ENCERRADA)
        tentativa = TentativaContato.objects.get()
        self.assertEqual((tentativa.canal, tentativa.resultado, tentativa.usuario),
                         (TentativaContato.Canal.LIGACAO, TentativaContato.Resultado.RESPONDEU, self.atendente))
        self.assertIn('Ligação feita · 40 s', Mensagem.objects.get(tipo=Mensagem.Tipo.CHAMADA).texto)

    def test_cliente_recusa(self):
        conversa = self.conversa_com_humano()
        self._ligar(conversa)
        chamada = Chamada.objects.get()

        processar_payload(_calls(statuses=[{'id': chamada.wa_call_id, 'type': 'call', 'status': 'REJECTED'}]))

        chamada.refresh_from_db()
        self.assertEqual(chamada.status, Chamada.Status.RECUSADA)
        self.assertIn('recusada', Mensagem.objects.get(tipo=Mensagem.Tipo.CHAMADA).texto)

    def test_desligar_e_pedir_permissao(self):
        conversa = self.conversa_com_humano()
        self._ligar(conversa)
        chamada = Chamada.objects.get()
        web = self.web(self.atendente)

        desligou = web.post(f'/crm/chamadas/{chamada.pk}/encerrar/', '{}', content_type=JSON)
        pediu = web.post(f'/crm/conversas/{conversa.pk}/pedir-permissao-ligacao/', '{}', content_type=JSON)

        self.assertEqual(desligou.json()['status'], Chamada.Status.PERDIDA)
        self.assertTrue(pediu.json()['ok'])
        self.assertTrue(Mensagem.objects.filter(dados__pedido_ligacao=True).exists())

    def test_resposta_do_cliente_ao_pedido_de_permissao_vira_texto(self):
        payload = {'entry': [{'changes': [{'field': 'messages', 'value': {'messages': [{
            'from': TELEFONE, 'id': 'wamid.perm', 'timestamp': '1767000000', 'type': 'interactive',
            'interactive': {'type': 'call_permission_reply',
                            'call_permission_reply': {'response': 'accept', 'is_permanent': False}},
        }]}}]}]}

        with self.captureOnCommitCallbacks(execute=True):
            processar_payload(payload)

        mensagem = Mensagem.objects.get(wa_message_id='wamid.perm')
        self.assertEqual(mensagem.texto, '📞 Autorizou receber ligações por 7 dias')
        self.assertTrue(mensagem.dados['permissao_ligacao']['aceitou'])


class TelasChamadaTests(CrmTestCase):
    def test_widget_e_botao_so_com_ligacoes_ativas(self):
        conversa = self.conversa_com_humano()
        desligadas = self.web(self.atendente, ajax=False).get(f'/crm/conversas/{conversa.pk}/')
        ConfiguracaoCRM.objects.filter(pk=1).update(chamadas_ativas=True)
        ligadas = self.web(self.atendente, ajax=False).get(f'/crm/conversas/{conversa.pk}/')

        self.assertNotContains(desligadas, 'id="crmLigacao"')
        self.assertContains(ligadas, 'id="crmLigacao"')
        self.assertContains(ligadas, f'data-ligar="/crm/conversas/{conversa.pk}/ligar/"')
        self.assertContains(ligadas, 'js/crm/chamadas.js')

    def test_gestor_ativa_as_ligacoes_no_numero(self):
        resposta = self.web(self.gestor, ajax=False).post('/crm/configuracao/ligacoes/ativar/')
        negado = self.web(self.atendente, ajax=False).post('/crm/configuracao/ligacoes/ativar/')

        self.assertEqual(resposta.status_code, 302)
        self.assertTrue(ConfiguracaoCRM.obter().chamadas_ativas)
        self.assertIn(negado.status_code, (302, 403))

    def test_sem_acesso_ao_crm_nao_mexe_em_ligacao(self):
        processar_payload(_calls(conexao_recebida()))
        chamada = Chamada.objects.get()

        resposta = self.web(self.sem_acesso).post(f'/crm/chamadas/{chamada.pk}/atender/', json.dumps({'sdp': SDP}),
                                                  content_type=JSON)

        self.assertIn(resposta.status_code, (302, 403))
        self.assertEqual(Chamada.objects.get().status, Chamada.Status.TOCANDO)
        self.assertIsNone(Conversa.objects.get().assumida_por)
