"""Configuração (`crm.gerenciar_crm`), apoio da caixa de entrada e simulador."""
import os
from unittest import mock

from crm.models import ConfiguracaoCRM, Conversa, Etiqueta, ModeloAbertura, RespostaRapida

from .base import CrmApiTestCase, url

COM_META = {'WHATSAPP_TOKEN': 'x', 'WHATSAPP_PHONE_NUMBER_ID': '1'}


class GeralTests(CrmApiTestCase):
    def test_situacao_da_integracao_sem_expor_valores(self):
        dados = self.api(self.gestor).get(url('configuracao/')).json()

        self.assertTrue(dados['simulado'])
        self.assertFalse(dados['integracao']['modo_real'])
        self.assertEqual({i['variavel'] for i in dados['integracao']['itens']} >= {'WHATSAPP_TOKEN'}, True)
        self.assertTrue(dados['integracao']['webhook_url'].endswith('/api/whatsapp/webhook/'))
        self.assertIn('nome_empresa', dados['configuracao'])

    def test_alterar_so_o_enviado_com_validacao_do_form_e_auditoria(self):
        api = self.api(self.gestor)

        invalida = api.patch(url('configuracao/'), {'retorno_automatico_horas': 1000, 'cnpj': '123'}, format='json')
        valida = api.patch(url('configuracao/'), {'nome_empresa': 'CredFacil', 'boas_vindas_ativa': False},
                           format='json')

        config = ConfiguracaoCRM.obter()
        self.assertEqual(invalida.status_code, 400)
        self.assertEqual(set(self.erro(invalida)['campos']), {'retorno_automatico_horas', 'cnpj'})
        self.assertEqual(valida.status_code, 200)
        self.assertEqual((config.nome_empresa, config.boas_vindas_ativa), ('CredFacil', False))
        self.assertEqual(config.autoatendimento_ativo, False)  # não enviado: continua como estava
        registro = self.auditorias('crm_configuracao_alterada').get()
        self.assertEqual(registro.dados['campos'], ['boas_vindas_ativa', 'nome_empresa'])


class CadastrosTests(CrmApiTestCase):
    def test_etiquetas(self):
        api = self.api(self.gestor)

        criada = api.post(url('configuracao/etiquetas/'), {'nome': 'Quente', 'cor': 'VERMELHO'}, format='json')
        repetida = api.post(url('configuracao/etiquetas/'), {'nome': 'quente', 'cor': 'AZUL'}, format='json')
        etiqueta_id = criada.json()['id']
        desativada = api.patch(url(f'configuracao/etiquetas/{etiqueta_id}/'), {'ativo': False}, format='json')
        lista = api.get(url('configuracao/etiquetas/')).json()
        ativas = self.api().get(url('etiquetas/')).json()

        self.assertEqual((criada.status_code, criada.json()['cor_display']), (201, 'Vermelho'))
        self.assertEqual(repetida.status_code, 400)
        self.assertIn('nome', self.erro(repetida)['campos'])
        self.assertEqual((desativada.json()['ativo'], desativada.json()['nome']), (False, 'Quente'))
        self.assertEqual(lista['count'], 1)
        self.assertEqual(ativas, [])
        self.assertEqual(self.auditorias('crm_etiqueta_criada').count(), 1)
        self.assertEqual(self.auditorias('crm_etiqueta_alterada').count(), 1)
        self.assertEqual(api.delete(url(f'configuracao/etiquetas/{etiqueta_id}/')).status_code, 405)
        self.assertTrue(Etiqueta.objects.filter(pk=etiqueta_id).exists())

    def test_respostas_rapidas(self):
        criada = self.api(self.gestor).post(url('configuracao/respostas-rapidas/'), {
            'atalho': '/Boleto', 'titulo': 'Boleto', 'texto': 'Olá {primeiro_nome}!'}, format='json')

        resposta = RespostaRapida.objects.get()
        self.assertEqual(criada.status_code, 201)
        self.assertEqual((resposta.atalho, resposta.criado_por), ('boleto', self.gestor))
        self.assertEqual(criada.json()['criado_por']['id'], self.gestor.pk)
        self.assertEqual(self.api().get(url('respostas-rapidas/')).json()[0]['atalho'], 'boleto')


class AberturasTests(CrmApiTestCase):
    def test_criar_simular_editar_e_verificar(self):
        api = self.api(self.gestor)

        invalida = api.post(url('configuracao/aberturas/'), {'titulo': 'Oi', 'corpo': '{nome}'}, format='json')
        criada = api.post(url('configuracao/aberturas/'),
                          {'titulo': 'Retomar contato', 'corpo': 'Olá {nome}, podemos continuar seu atendimento?'},
                          format='json')
        abertura_id = criada.json()['id']
        aprovada = api.post(url(f'configuracao/aberturas/{abertura_id}/simular/'), {'status': 'APROVADO'},
                            format='json')
        disponiveis = self.api().get(url('aberturas/')).json()
        editada = api.patch(url(f'configuracao/aberturas/{abertura_id}/'),
                            {'corpo': 'Oi {nome}, vamos continuar seu atendimento por aqui?', 'ordem': 2},
                            format='json')
        verificada = api.post(url(f'configuracao/aberturas/{abertura_id}/verificar/'))

        self.assertEqual(invalida.status_code, 400)
        self.assertEqual(set(self.erro(invalida)['campos']), {'titulo', 'corpo'})
        self.assertEqual(criada.status_code, 201)
        self.assertEqual(criada.json()['em_analise']['status'], 'EM_ANALISE')
        self.assertEqual(aprovada.json()['vigente']['status'], 'APROVADO')
        self.assertTrue(disponiveis[0]['disponivel'])
        self.assertTrue(disponiveis[0]['usa_nome'])
        self.assertEqual(editada.status_code, 200)
        self.assertEqual((editada.json()['ordem'], editada.json()['em_analise']['versao']), (2, 2))
        self.assertEqual(editada.json()['vigente']['versao'], 1)  # a anterior vale até a Meta decidir
        self.assertEqual(verificada.status_code, 200)
        self.assertEqual(ModeloAbertura.objects.get().versoes.count(), 2)
        self.assertEqual(self.auditorias('crm_abertura_criada').count(), 1)

    def test_editar_sem_mudar_o_texto_nao_cria_versao(self):
        modelo = self.abertura_aprovada('Retomar contato', 'Olá {nome}, podemos continuar seu atendimento?')

        resposta = self.api(self.gestor).patch(url(f'configuracao/aberturas/{modelo.pk}/'), {
            'corpo': 'Olá {nome}, podemos continuar seu atendimento?', 'titulo': 'Retomar'}, format='json')

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()['titulo'], 'Retomar')
        self.assertEqual(modelo.versoes.count(), 1)

    def test_simular_com_credenciais_da_meta_recebe_409(self):
        modelo = self.abertura_aprovada('Retomar contato', 'Olá {nome}, podemos continuar seu atendimento?')

        with mock.patch.dict(os.environ, COM_META):
            resposta = self.api(self.gestor).post(url(f'configuracao/aberturas/{modelo.pk}/simular/'),
                                                  {'status': 'APROVADO'}, format='json')

        self.assertEqual(resposta.status_code, 409)


class SimuladorTests(CrmApiTestCase):
    def test_receber_e_ler(self):
        api = self.api(self.gestor)

        with self.em_commit():
            recebida = api.post(url('configuracao/simulador/receber/'),
                                {'telefone': '5591977776666', 'nome': 'Teste', 'texto': 'Oi'}, format='json')
        conversa_id = recebida.json()['conversa_id']
        lida = api.post(url('configuracao/simulador/ler/'), {'conversa': conversa_id}, format='json')
        painel = api.get(url('configuracao/simulador/')).json()

        self.assertEqual(recebida.status_code, 201)
        self.assertEqual(recebida.json()['mensagem']['texto'], 'Oi')
        self.assertEqual(Conversa.objects.get(pk=conversa_id).modo, 'AGUARDANDO')  # boas-vindas + fila
        self.assertEqual(lida.json()['alteradas'], 1)
        self.assertTrue(painel['disponivel'])
        self.assertEqual(painel['conversas'][0]['id'], conversa_id)

    def test_com_credenciais_da_meta_recebe_409(self):
        with mock.patch.dict(os.environ, COM_META):
            resposta = self.api(self.gestor).post(url('configuracao/simulador/receber/'),
                                                  {'telefone': '5591977776666', 'texto': 'Oi'}, format='json')

        self.assertEqual(resposta.status_code, 409)
        self.assertFalse(Conversa.objects.exists())


class ApoioTests(CrmApiTestCase):
    def test_contexto_e_atendentes(self):
        contexto = self.api().get(url('contexto/')).json()
        atendentes = self.api().get(url('atendentes/')).json()

        self.assertTrue(contexto['simulado'])
        self.assertFalse(contexto['pode_gerenciar'])
        self.assertFalse(contexto['ve_clientes'])
        self.assertEqual(contexto['limites']['arquivo_bytes'], 25 * 1024 * 1024)
        self.assertEqual([f['valor'] for f in contexto['filas']], ['minhas', 'sem_dono', 'automatico', 'todas'])
        ids = {a['id'] for a in atendentes}
        self.assertTrue({self.atendente.pk, self.gestor.pk} <= ids)
        self.assertNotIn(self.sem_acesso.pk, ids)
        self.assertTrue(self.api(self.gestor).get(url('contexto/')).json()['pode_gerenciar'])
