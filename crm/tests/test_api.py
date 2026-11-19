import io
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from crm.models import Conversa, Etiqueta, LogAcessoMidia, Mensagem, MensagemProgramada, Nota, RespostaRapida
from crm.services import organizacao
from crm.tests.base import CrmTestCase, fechar_janela
from vendas.models import Cliente, ComprovantesCliente, Loja


def _png() -> bytes:
    from PIL import Image

    saida = io.BytesIO()
    Image.new('RGB', (40, 30), 'red').save(saida, format='PNG')
    return saida.getvalue()


class PermissaoTests(CrmTestCase):
    def test_sem_permissao_recebe_403_em_todo_o_crm(self):
        cliente = self.api(self.sem_acesso)
        rotas = ['/api/crm/conversas/', '/api/crm/conversas/contadores/', '/api/crm/etiquetas/',
                 '/api/crm/configuracao/', '/api/crm/atendentes/', '/api/crm/aberturas/disponiveis/']

        for rota in rotas:
            with self.subTest(rota=rota):
                self.assertEqual(cliente.get(rota).status_code, 403)

    def test_staff_sem_a_permissao_nao_ve_o_crm(self):
        staff = self.criar_usuario('staff', is_staff=True)

        self.assertEqual(self.api(staff).get('/api/crm/conversas/').status_code, 403)

    def test_superusuario_ve_o_crm(self):
        admin = self.criar_usuario('admin', is_superuser=True)

        self.assertEqual(self.api(admin).get('/api/crm/conversas/').status_code, 200)

    def test_cadastros_e_integracao_exigem_gerenciar(self):
        atendente = self.api(self.atendente)
        gestor = self.api(self.gestor)

        self.assertEqual(atendente.post('/api/crm/etiquetas/', {'nome': 'VIP'}).status_code, 403)
        self.assertEqual(atendente.get('/api/crm/integracao/').status_code, 403)
        self.assertEqual(gestor.post('/api/crm/etiquetas/', {'nome': 'VIP'}).status_code, 201)
        integracao = gestor.get('/api/crm/integracao/').json()
        self.assertEqual(integracao['modo'], 'simulado')
        self.assertTrue(integracao['webhook_url'].endswith('/api/whatsapp/webhook/'))
        self.assertTrue(integracao['pendencias'])

    def test_flags_do_crm_vem_no_usuario_logado(self):
        atendente = self.api(self.atendente).get('/api/usuarios/me/').json()['acessos']
        staff = self.api(self.criar_usuario('staff', is_staff=True)).get('/api/usuarios/me/').json()['acessos']

        self.assertTrue(atendente['pode_acessar_crm'])
        self.assertFalse(atendente['pode_gerenciar_crm'])
        self.assertFalse(staff['pode_acessar_crm'])

    def test_permissao_aparece_no_admin_de_grupos(self):
        from django.contrib.auth.models import Permission

        nomes = set(Permission.objects.filter(content_type__app_label='crm').values_list('name', flat=True))

        self.assertEqual(nomes, {'Pode acessar o CRM de WhatsApp', 'Pode gerenciar o CRM de WhatsApp'})


class ConversasApiTests(CrmTestCase):
    def test_lista_filas_e_contadores(self):
        self.receber('Oi', telefone='5591999990001')
        self.conversa_com_humano()
        api = self.api(self.atendente)

        minhas = api.get('/api/crm/conversas/', {'fila': 'minhas'}).json()
        sem_dono = api.get('/api/crm/conversas/', {'fila': 'sem_dono'}).json()
        contadores = api.get('/api/crm/conversas/contadores/').json()

        self.assertEqual(minhas['count'], 1)
        self.assertEqual(sem_dono['count'], 1)
        self.assertEqual(contadores['todas'], 2)
        item = sem_dono['results'][0]
        self.assertTrue(item['janela_aberta'])
        self.assertIsNotNone(item['motivo_transferencia'])
        self.assertEqual(item['modo'], 'AGUARDANDO')

    def test_busca_por_texto_da_mensagem_e_telefone(self):
        self.receber('Quero um iPhone 15', telefone='5591988887777')
        api = self.api(self.atendente)

        por_texto = api.get('/api/crm/conversas/', {'search': 'iphone'}).json()['count']
        por_telefone = api.get('/api/crm/conversas/', {'search': '88887777'}).json()['count']

        self.assertEqual((por_texto, por_telefone), (1, 1))

    def test_detalhe_zera_nao_lidas_e_informa_bloqueio(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()

        detalhe = self.api(self.atendente).get(f'/api/crm/conversas/{conversa.pk}/').json()

        conversa.refresh_from_db()
        self.assertEqual(conversa.nao_lidas, 0)
        self.assertEqual(detalhe['bloqueio']['motivo'], 'NAO_ASSUMIDA')
        self.assertFalse(detalhe['pode_responder'])
        self.assertEqual(len(detalhe['notas']), 1)

    def test_fluxo_assumir_enviar_resolver(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        api = self.api(self.atendente)

        sem_assumir = api.post(f'/api/crm/conversas/{conversa.pk}/enviar/', {'texto': 'Olá'}, format='json')
        assumida = api.post(f'/api/crm/conversas/{conversa.pk}/assumir/').json()
        enviada = api.post(f'/api/crm/conversas/{conversa.pk}/enviar/', {'texto': 'Olá, Maria!'}, format='json')
        resolvida = api.post(f'/api/crm/conversas/{conversa.pk}/situacao/',
                             {'situacao': 'RESOLVIDA', 'devolver_automatico': True}, format='json').json()

        self.assertEqual(sem_assumir.status_code, 409)
        self.assertEqual(assumida['assumida_por']['id'], self.atendente.pk)
        self.assertEqual(enviada.status_code, 201)
        self.assertEqual(enviada.json()['status'], 'ENVIADO')
        self.assertEqual((resolvida['situacao'], resolvida['modo']), ('RESOLVIDA', 'AUTOMATICO'))

    def test_janela_fechada_bloqueia_texto_e_libera_abertura_aprovada(self):
        conversa = self.conversa_com_humano()
        fechar_janela(conversa)
        gestor, atendente = self.api(self.gestor), self.api(self.atendente)
        criada = gestor.post('/api/crm/aberturas/', {'titulo': 'Retomar contato',
                                                     'corpo': 'Olá {nome}, podemos continuar seu atendimento?'},
                             format='json').json()
        gestor.post(f'/api/crm/aberturas/{criada["id"]}/simular/', {'status': 'APROVADO'}, format='json')

        texto = atendente.post(f'/api/crm/conversas/{conversa.pk}/enviar/', {'texto': 'Oi'}, format='json')
        abertura = atendente.post(f'/api/crm/conversas/{conversa.pk}/abrir/', {'modelo': criada['chave']}, format='json')

        self.assertEqual(texto.status_code, 409)
        self.assertEqual(abertura.status_code, 200)
        enviada = Mensagem.objects.get(origem=Mensagem.Origem.ABERTURA)
        self.assertEqual(enviada.texto, 'Olá Maria, podemos continuar seu atendimento?')
        self.assertEqual(abertura.json()['situacao'], 'PENDENTE')

    def test_iniciar_conversa_com_numero_novo(self):
        gestor = self.api(self.gestor)
        criada = gestor.post('/api/crm/aberturas/', {'titulo': 'Boas notícias',
                                                     'corpo': 'Olá {nome}, temos uma novidade sobre seu pedido.'},
                             format='json').json()
        gestor.post(f'/api/crm/aberturas/{criada["id"]}/simular/', {'status': 'APROVADO'}, format='json')

        resposta = gestor.post('/api/crm/conversas/iniciar/',
                               {'telefone': '(91) 98888-1111', 'modelo': criada['chave'], 'nome': 'João Lima'},
                               format='json')

        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['telefone'], '5591988881111')
        self.assertEqual(resposta.json()['assumida_por']['id'], self.gestor.pk)

    def test_atribuir_e_notas(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        gestor, atendente = self.api(self.gestor), self.api(self.atendente)

        sem_poder = atendente.post(f'/api/crm/conversas/{conversa.pk}/atribuir/', {'usuario': self.outro.pk}, format='json')
        atribuida = gestor.post(f'/api/crm/conversas/{conversa.pk}/atribuir/', {'usuario': self.outro.pk}, format='json')
        nota = atendente.post(f'/api/crm/conversas/{conversa.pk}/notas/', {'texto': 'Cliente prefere à tarde'}, format='json')
        apagar_alheia = gestor.delete(f'/api/crm/conversas/{conversa.pk}/notas/{nota.json()["id"]}/')
        apagar_propria = atendente.delete(f'/api/crm/conversas/{conversa.pk}/notas/{nota.json()["id"]}/')

        self.assertEqual(sem_poder.status_code, 409)
        self.assertEqual(atribuida.json()['assumida_por']['id'], self.outro.pk)
        self.assertEqual(apagar_alheia.status_code, 409)
        self.assertEqual(apagar_propria.status_code, 204)
        self.assertIsNotNone(Nota.objects.get(pk=nota.json()['id']).apagada_em)

    def test_etiquetas_lembrete_e_apelido(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        etiqueta = Etiqueta.objects.create(nome='Quente', cor='VERMELHO')
        api = self.api(self.atendente)
        amanha = (timezone.now() + timedelta(days=1)).isoformat()

        api.post(f'/api/crm/conversas/{conversa.pk}/etiquetas/', {'etiquetas': [etiqueta.pk]}, format='json')
        api.put(f'/api/crm/conversas/{conversa.pk}/lembrete/', {'lembrete_em': amanha, 'texto': 'Ligar'}, format='json')
        detalhe = api.patch(f'/api/crm/conversas/{conversa.pk}/apelido/', {'apelido': 'Dona Maria'}, format='json').json()

        self.assertEqual([e['nome'] for e in detalhe['etiquetas']], ['Quente'])
        self.assertEqual(detalhe['lembrete']['texto'], 'Ligar')
        self.assertEqual(detalhe['nome_exibicao'], 'Dona Maria')

    def test_programada_e_resposta_rapida(self):
        conversa = self.conversa_com_humano()
        resposta = RespostaRapida.objects.create(atalho='oi', titulo='Saudação', texto='Olá {primeiro_nome}, sou {atendente} da {empresa}.')
        api = self.api(self.atendente)

        cedo = api.post(f'/api/crm/conversas/{conversa.pk}/programadas/',
                        {'texto': 'Lembrete', 'enviar_em': timezone.now().isoformat()}, format='json')
        criada = api.post(f'/api/crm/conversas/{conversa.pk}/programadas/',
                          {'texto': 'Lembrete', 'enviar_em': (timezone.now() + timedelta(hours=2)).isoformat()},
                          format='json')
        previa = api.post(f'/api/crm/conversas/{conversa.pk}/respostas-rapidas/{resposta.pk}/previa/').json()
        cancelada = api.post(f'/api/crm/programadas/{criada.json()["id"]}/cancelar/')

        self.assertEqual(cedo.status_code, 409)
        self.assertEqual(criada.status_code, 201)
        self.assertEqual(previa['texto'], 'Olá Maria, sou Ana da IPX.')
        self.assertEqual(cancelada.json()['status'], 'CANCELADA')

    def test_envio_de_imagem_e_url_assinada(self):
        conversa = self.conversa_com_humano()
        api = self.api(self.atendente)
        arquivo = SimpleUploadedFile('foto.png', _png(), content_type='image/png')

        with self.captureOnCommitCallbacks(execute=True):
            enviada = api.post(f'/api/crm/conversas/{conversa.pk}/enviar-midia/', {'arquivo': arquivo, 'legenda': 'Veja'},
                               format='multipart')
        mensagem = Mensagem.objects.get(pk=enviada.json()['id'])
        url = api.get(f'/api/crm/mensagens/{mensagem.pk}/arquivo/').json()['url']
        download = self.client.get(url.replace('http://testserver', ''))

        self.assertEqual(enviada.status_code, 201)
        self.assertEqual(mensagem.status, Mensagem.Status.ENVIADO)
        self.assertEqual(mensagem.tipo, Mensagem.Tipo.IMAGEM)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(LogAcessoMidia.objects.count(), 1)
        self.assertEqual(self.client.get('/api/crm/midia/token-falso/').status_code, 404)

    def test_heic_e_recusado(self):
        conversa = self.conversa_com_humano()
        heic = b'\x00\x00\x00\x18ftypheic' + b'\x00' * 64

        resposta = self.api(self.atendente).post(
            f'/api/crm/conversas/{conversa.pk}/enviar-midia/',
            {'arquivo': SimpleUploadedFile('foto.heic', heic)}, format='multipart')

        self.assertEqual(resposta.status_code, 409)

    def test_painel_sugere_e_vincula_cliente_pelo_telefone(self):
        loja = Loja.objects.create(nome='Loja')
        cliente = Cliente.objects.create(
            nome='Maria Souza', telefone='(91) 99999-0000', cpf='12345678900', nascimento='1990-01-01', rg='1',
            cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
            comprovantes=ComprovantesCliente.objects.create(loja=loja),
        )
        self.receber('Oi', telefone='559199990000')
        conversa = Conversa.objects.get()
        api = self.api(self.atendente)

        sugeridos = api.get(f'/api/crm/conversas/{conversa.pk}/painel/').json()['sugeridos']
        detalhe = api.post(f'/api/crm/conversas/{conversa.pk}/vincular-cliente/', {'cliente': cliente.pk}, format='json').json()
        painel = api.get(f'/api/crm/conversas/{conversa.pk}/painel/').json()

        self.assertEqual([s['id'] for s in sugeridos], [cliente.pk])
        self.assertEqual(detalhe['clientes'], [{'id': cliente.pk, 'nome': 'Maria Souza'}])
        self.assertEqual(painel['clientes'][0]['nome'], 'Maria Souza')
        self.assertEqual(painel['sugeridos'], [])

    def test_simulador(self):
        gestor = self.api(self.gestor)

        with self.captureOnCommitCallbacks(execute=True):
            recebida = gestor.post('/api/crm/simulador/receber/',
                                   {'telefone': '5591977776666', 'nome': 'Teste', 'texto': 'Oi'}, format='json')

        self.assertEqual(recebida.status_code, 201)
        conversa = Conversa.objects.get(pk=recebida.json()['conversa_id'])
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertEqual(self.api(self.atendente).post('/api/crm/simulador/receber/', {}, format='json').status_code, 403)


class RotinasTests(CrmTestCase):
    def test_programada_vencida_sai_e_janela_fechada_vira_erro_com_nota(self):
        conversa = self.conversa_com_humano()
        ok = MensagemProgramada.objects.create(conversa=conversa, criado_por=self.atendente, texto='Bom dia!',
                                               enviar_em=timezone.now() - timedelta(minutes=1))
        enviadas = organizacao.enviar_programadas_vencidas()
        fechar_janela(conversa)
        falha = MensagemProgramada.objects.create(conversa=conversa, criado_por=self.atendente, texto='Oi',
                                                  enviar_em=timezone.now() - timedelta(minutes=1))
        organizacao.enviar_programadas_vencidas()

        ok.refresh_from_db()
        falha.refresh_from_db()
        self.assertEqual(enviadas, 1)
        self.assertEqual(ok.status, MensagemProgramada.Status.ENVIADA)
        self.assertEqual(falha.status, MensagemProgramada.Status.ERRO)
        self.assertTrue(Nota.objects.filter(conversa=conversa, texto__icontains='programada').exists())

    def test_rodar_tudo_e_envio_travado(self):
        from crm.services.rotinas import rodar_tudo

        conversa = self.conversa_com_humano()
        travada = Mensagem.objects.create(conversa=conversa, direcao='SAIDA', autor='HUMANO', texto='x',
                                          status='PENDENTE', envio_iniciado_em=timezone.now() - timedelta(minutes=15))

        resultado = rodar_tudo()

        travada.refresh_from_db()
        self.assertNotIn('erro', resultado.values())
        self.assertEqual(travada.status, Mensagem.Status.ERRO)
