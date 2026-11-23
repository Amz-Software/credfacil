"""Acesso ao CRM no backoffice e telas de configuração (só quem gerencia)."""
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from crm.models import ConfiguracaoCRM, Conversa, Etiqueta, ModeloAbertura, RespostaRapida
from crm.tests.base import CrmTestCase


class AcessoTests(CrmTestCase):
    def test_sem_permissao_recebe_403_em_todo_o_crm(self):
        conversa = self.receber('Oi').conversa
        web = self.web(self.sem_acesso)
        rotas = ['/crm/', '/crm/lista/', f'/crm/conversas/{conversa.pk}/',
                 f'/crm/conversas/{conversa.pk}/parte/mensagens/', '/crm/configuracao/']

        for rota in rotas:
            with self.subTest(rota=rota):
                self.assertEqual(web.get(rota).status_code, 403)
        self.assertEqual(web.post(f'/crm/conversas/{conversa.pk}/assumir/').status_code, 403)

    def test_anonimo_vai_para_o_login(self):
        resposta = self.client.get('/crm/')

        self.assertEqual(resposta.status_code, 302)
        self.assertIn('/login', resposta.url)

    def test_staff_sem_a_permissao_nao_ve_o_crm(self):
        staff = self.criar_usuario('staff', is_staff=True)

        self.assertEqual(self.web(staff).get('/crm/').status_code, 403)

    def test_superusuario_ve_o_crm(self):
        admin = self.criar_usuario('admin', is_superuser=True)

        self.assertEqual(self.web(admin).get('/crm/').status_code, 200)

    def test_api_da_spa_nao_tem_crm(self):
        """O app do vendedor (JWT em /api/) não alcança o CRM nem recebe flags dele."""
        api = APIClient()
        api.force_authenticate(self.atendente)

        acessos = api.get('/api/usuarios/me/').json()['acessos']

        self.assertEqual(api.get('/api/crm/conversas/').status_code, 404)
        self.assertNotIn('pode_acessar_crm', acessos)

    def test_menu_mostra_o_crm_conforme_a_permissao(self):
        atendente = self.web(self.atendente, ajax=False).get('/crm/')
        gestor = self.web(self.gestor, ajax=False).get('/crm/')

        self.assertContains(atendente, 'CRM WhatsApp')
        self.assertNotContains(atendente, 'href="/crm/configuracao/"')
        self.assertContains(gestor, 'href="/crm/configuracao/"')

    def test_permissoes_aparecem_no_cadastro_de_grupos(self):
        nomes = set(Permission.objects.filter(content_type__app_label='crm').values_list('name', flat=True))

        self.assertEqual(nomes, {'Pode acessar o CRM de WhatsApp', 'Pode gerenciar o CRM de WhatsApp'})


class ConfiguracaoTests(CrmTestCase):
    def test_atendente_nao_configura(self):
        web = self.web(self.atendente, ajax=False)

        for rota in ('/crm/configuracao/', '/crm/configuracao/etiquetas/', '/crm/configuracao/aberturas/',
                     '/crm/configuracao/simulador/'):
            with self.subTest(rota=rota):
                self.assertEqual(web.get(rota).status_code, 403)
        self.assertEqual(web.post('/crm/configuracao/etiquetas/', {'nome': 'VIP', 'cor': 'AZUL'}).status_code, 403)
        self.assertFalse(Etiqueta.objects.exists())

    def test_geral_mostra_integracao_sem_segredos_e_valida_endereco(self):
        web = self.web(self.gestor, ajax=False)
        dados = {'nome_empresa': 'IPX', 'mensagem_boas_vindas': 'Olá!', 'retorno_automatico_horas': '24',
                 'autoatendimento_ativo': 'on'}

        pagina = web.get('/crm/configuracao/')
        invalido = web.post('/crm/configuracao/', {**dados, 'url_publica': 'http://inseguro.com'})
        valido = web.post('/crm/configuracao/', {**dados, 'url_publica': 'https://credfacil.exemplo.com/'})

        self.assertContains(pagina, 'WHATSAPP_TOKEN')
        self.assertContains(pagina, '/api/whatsapp/webhook/')
        self.assertContains(invalido, 'https://')
        self.assertEqual(valido.status_code, 302)
        self.assertEqual(ConfiguracaoCRM.obter().url_publica, 'https://credfacil.exemplo.com')

    def test_etiquetas_e_respostas(self):
        web = self.web(self.gestor, ajax=False)

        web.post('/crm/configuracao/etiquetas/', {'nome': 'VIP', 'cor': 'AZUL', 'ordem': '0', 'ativo': 'on'})
        repetida = web.post('/crm/configuracao/etiquetas/', {'nome': 'vip', 'cor': 'VERDE', 'ordem': '0'})
        web.post('/crm/configuracao/respostas/', {'atalho': ' /Boleto ', 'titulo': 'Boleto', 'texto': 'Segue.',
                                                   'ordem': '0', 'ativo': 'on'})
        etiqueta = Etiqueta.objects.get()
        web.post(f'/crm/configuracao/etiquetas/{etiqueta.pk}/', {'nome': 'VIP', 'cor': 'AZUL', 'ordem': '1'})

        etiqueta.refresh_from_db()
        self.assertContains(repetida, 'Já existe uma etiqueta com esse nome.')
        self.assertEqual(RespostaRapida.objects.get().atalho, 'boleto')
        self.assertEqual(RespostaRapida.objects.get().criado_por, self.gestor)
        self.assertFalse(etiqueta.ativo)
        self.assertEqual(web.get('/crm/configuracao/outra-coisa/').status_code, 404)

    def test_abertura_editar_so_reenvia_quando_o_texto_muda(self):
        modelo = self.abertura_aprovada('Retomar', 'Olá {nome}, podemos continuar seu atendimento?')
        web = self.web(self.gestor, ajax=False)
        url = f'/crm/configuracao/aberturas/{modelo.pk}/'

        web.post(url, {'titulo': 'Retomar contato', 'corpo': 'Olá {nome}, podemos continuar seu atendimento?',
                       'ordem': '2', 'ativo': 'on'})
        versoes_sem_mudar = modelo.versoes.count()
        web.post(url, {'titulo': 'Retomar contato', 'corpo': 'Olá {nome}, vamos retomar o seu atendimento?',
                       'ordem': '2', 'ativo': 'on'})

        modelo.refresh_from_db()
        self.assertEqual((modelo.titulo, modelo.ordem), ('Retomar contato', 2))
        self.assertEqual(versoes_sem_mudar, 1)
        self.assertEqual(modelo.versoes.count(), 2)

    def test_abertura_invalida_mostra_erro(self):
        resposta = self.web(self.gestor, ajax=False).post(
            '/crm/configuracao/aberturas/', {'titulo': 'Teste', 'corpo': '{nome}'})

        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(ModeloAbertura.objects.exists())

    def test_simulador_recebe_como_cliente_e_mostra_a_resposta(self):
        web = self.web(self.gestor, ajax=False)

        with self.captureOnCommitCallbacks(execute=True):
            web.post('/crm/configuracao/simulador/', {'telefone': '5591977776666', 'nome': 'Teste', 'texto': 'Oi'})
        pagina = web.get('/crm/configuracao/simulador/')

        conversa = Conversa.objects.get(telefone='5591977776666')
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertEqual(pagina.context['conversa_simulada']['id'], conversa.pk)
        self.assertContains(pagina, 'value="5591977776666"')
        self.assertEqual(self.web(self.atendente).post('/crm/configuracao/simulador/', {}).status_code, 403)


class PoliticaPrivacidadeTests(CrmTestCase):
    def test_pagina_publica_com_os_dados_da_empresa(self):
        web = self.web(self.gestor, ajax=False)
        web.post('/crm/configuracao/', {
            'nome_empresa': 'IPX', 'mensagem_boas_vindas': 'Olá!', 'retorno_automatico_horas': '24',
            'razao_social': 'IPX Serviços LTDA', 'cnpj': '12345678000190', 'email_privacidade': 'dados@ipx.com.br',
        })

        resposta = self.client.get('/privacidade/')

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'IPX Serviços LTDA')
        self.assertContains(resposta, '12.345.678/0001-90')
        self.assertContains(resposta, 'mailto:dados@ipx.com.br')

    def test_cnpj_invalido_e_recusado(self):
        resposta = self.web(self.gestor, ajax=False).post('/crm/configuracao/', {
            'nome_empresa': 'IPX', 'mensagem_boas_vindas': 'Olá!', 'retorno_automatico_horas': '24', 'cnpj': '123'})

        self.assertContains(resposta, 'O CNPJ tem 14 dígitos.')

    def test_configuracao_mostra_o_endereco_da_politica(self):
        self.assertContains(self.web(self.gestor, ajax=False).get('/crm/configuracao/'), '/privacidade/')
