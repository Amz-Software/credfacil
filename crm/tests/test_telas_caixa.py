"""Caixa de entrada do CRM no backoffice: filas, conversa, ações, envio, painel e mídia."""
import io
from datetime import timedelta

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from crm.models import Conversa, Etiqueta, LogAcessoMidia, Mensagem, MensagemProgramada, Nota, RespostaRapida
from crm.tests.base import CrmTestCase, fechar_janela
from vendas.models import Cliente, ComprovantesCliente, Loja


def _png() -> bytes:
    from PIL import Image

    saida = io.BytesIO()
    Image.new('RGB', (40, 30), 'red').save(saida, format='PNG')
    return saida.getvalue()


def _local(delta: timedelta) -> str:
    """Formato do <input type="datetime-local"> no fuso do sistema."""
    return timezone.localtime(timezone.now() + delta).strftime('%Y-%m-%dT%H:%M')


class ListaTests(CrmTestCase):
    def test_filas_e_contadores(self):
        self.receber('Oi', telefone='5591999990001')
        self.conversa_com_humano()
        web = self.web(self.atendente)

        minhas = web.get('/crm/lista/', {'fila': 'minhas'}).context
        sem_dono = web.get('/crm/lista/', {'fila': 'sem_dono'}).context

        self.assertEqual(len(minhas['conversas']), 1)
        self.assertEqual(len(sem_dono['conversas']), 1)
        self.assertEqual(minhas['contadores']['todas'], 2)
        item = sem_dono['conversas'][0]
        self.assertTrue(item['janela_aberta'])
        self.assertIsNotNone(item['motivo_transferencia'])
        self.assertEqual(item['modo'], 'AGUARDANDO')

    def test_busca_por_texto_e_telefone(self):
        self.receber('Quero um iPhone 15', telefone='5591988887777')
        web = self.web(self.atendente)

        por_texto = web.get('/crm/lista/', {'fila': 'todas', 'q': 'iphone'}).context['conversas']
        por_telefone = web.get('/crm/lista/', {'fila': 'todas', 'q': '88887777'}).context['conversas']

        self.assertEqual((len(por_texto), len(por_telefone)), (1, 1))

    def test_pagina_da_caixa_sem_conversa(self):
        resposta = self.web(self.atendente, ajax=False).get('/crm/')

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Escolha uma conversa')
        self.assertContains(resposta, 'js/crm/caixa.js')


class ConversaTests(CrmTestCase):
    def test_abrir_zera_nao_lidas_e_mostra_bloqueio(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()

        resposta = self.web(self.atendente, ajax=False).get(f'/crm/conversas/{conversa.pk}/')

        conversa.refresh_from_db()
        self.assertEqual(conversa.nao_lidas, 0)
        detalhe = resposta.context['conversa']
        self.assertEqual(detalhe['bloqueio']['motivo'], 'NAO_ASSUMIDA')
        self.assertFalse(detalhe['pode_responder'])
        self.assertEqual(len(detalhe['notas']), 1)
        self.assertContains(resposta, 'Assuma a conversa antes de responder.')

    def test_texto_do_cliente_e_escapado(self):
        self.receber('<script>alert(1)</script>')
        conversa = Conversa.objects.get()

        resposta = self.web(self.atendente, ajax=False).get(f'/crm/conversas/{conversa.pk}/')

        self.assertNotContains(resposta, '<script>alert(1)</script>')
        self.assertContains(resposta, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_partes_recarregaveis(self):
        conversa = self.conversa_com_humano()
        web = self.web(self.atendente)

        for nome in ('cabecalho', 'mensagens', 'compositor', 'painel'):
            with self.subTest(parte=nome):
                self.assertEqual(web.get(f'/crm/conversas/{conversa.pk}/parte/{nome}/').status_code, 200)
        self.assertEqual(web.get(f'/crm/conversas/{conversa.pk}/parte/outra/').status_code, 404)

    def test_mensagens_antigas_em_paginas(self):
        conversa = self.conversa_com_humano()
        for i in range(60):
            Mensagem.objects.create(conversa=conversa, direcao='SAIDA', autor='HUMANO', texto=f'm{i}', status='ENVIADO')
        web = self.web(self.atendente)

        pagina = web.get(f'/crm/conversas/{conversa.pk}/parte/mensagens/').context['conversa']
        antigas = web.get(f'/crm/conversas/{conversa.pk}/mensagens/', {'antes': pagina['mensagens'][0]['id']}).context

        self.assertTrue(pagina['tem_mais_antigas'])
        self.assertEqual(len(pagina['mensagens']), 50)
        self.assertFalse(antigas['tem_mais_antigas'])
        self.assertEqual(len(antigas['mensagens']) + 50, Mensagem.objects.filter(conversa=conversa).count())


class AcoesTests(CrmTestCase):
    def test_fluxo_assumir_enviar_resolver(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        web = self.web(self.atendente)
        base = f'/crm/conversas/{conversa.pk}/'

        sem_assumir = web.post(f'{base}enviar/', {'texto': 'Olá'})
        assumida = web.post(f'{base}assumir/')
        enviada = web.post(f'{base}enviar/', {'texto': 'Olá, Maria!'})
        web.post(f'{base}situacao/', {'situacao': 'RESOLVIDA', 'devolver_automatico': '1'})

        conversa.refresh_from_db()
        self.assertEqual(sem_assumir.status_code, 409)
        self.assertEqual(sem_assumir.json()['motivo'], 'NAO_ASSUMIDA')
        self.assertTrue(assumida.json()['ok'])
        self.assertEqual(enviada.status_code, 200)
        saida = Mensagem.objects.get(direcao='SAIDA', autor='HUMANO')
        self.assertEqual((saida.texto, saida.status), ('Olá, Maria!', Mensagem.Status.ENVIADO))
        self.assertEqual((conversa.situacao, conversa.modo), ('RESOLVIDA', 'AUTOMATICO'))

    def test_sem_js_volta_para_a_conversa_com_mensagem(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        web = self.web(self.atendente, ajax=False)

        ok = web.post(f'/crm/conversas/{conversa.pk}/assumir/', {'proxima': 'https://site-malicioso.com/'})
        erro = web.post(f'/crm/conversas/{conversa.pk}/puxar/', follow=True)

        self.assertRedirects(ok, f'/crm/conversas/{conversa.pk}/', fetch_redirect_response=False)
        self.assertContains(erro, 'A conversa já está com você.')

    def test_acoes_so_aceitam_post(self):
        conversa = self.conversa_com_humano()

        self.assertEqual(self.web(self.atendente).get(f'/crm/conversas/{conversa.pk}/assumir/').status_code, 405)

    def test_janela_fechada_bloqueia_texto_e_libera_abertura_aprovada(self):
        conversa = self.conversa_com_humano()
        fechar_janela(conversa)
        modelo = self.abertura_aprovada('Retomar contato', 'Olá {nome}, podemos continuar seu atendimento?')
        web = self.web(self.atendente)

        texto = web.post(f'/crm/conversas/{conversa.pk}/enviar/', {'texto': 'Oi'})
        abertura = web.post(f'/crm/conversas/{conversa.pk}/abrir/', {'modelo': modelo.chave})

        conversa.refresh_from_db()
        self.assertEqual(texto.status_code, 409)
        self.assertEqual(abertura.status_code, 200)
        enviada = Mensagem.objects.get(origem=Mensagem.Origem.ABERTURA)
        self.assertEqual(enviada.texto, 'Olá Maria, podemos continuar seu atendimento?')
        self.assertEqual(conversa.situacao, 'PENDENTE')

    def test_iniciar_conversa_com_numero_novo(self):
        modelo = self.abertura_aprovada('Boas notícias', 'Olá {nome}, temos uma novidade sobre seu pedido.')

        resposta = self.web(self.gestor).post('/crm/iniciar/', {
            'telefone': '(91) 98888-1111', 'modelo': modelo.chave, 'nome': 'João Lima'})

        conversa = Conversa.objects.get(telefone='5591988881111')
        self.assertEqual(resposta.json()['redirecionar'], f'/crm/conversas/{conversa.pk}/')
        self.assertEqual(conversa.assumida_por, self.gestor)

    def test_atribuir_e_notas(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        gestor, atendente = self.web(self.gestor), self.web(self.atendente)
        base = f'/crm/conversas/{conversa.pk}/'

        sem_poder = atendente.post(f'{base}atribuir/', {'usuario': self.outro.pk})
        gestor.post(f'{base}atribuir/', {'usuario': self.outro.pk})
        atendente.post(f'{base}notas/', {'texto': 'Cliente prefere à tarde'})
        nota = Nota.objects.get(texto='Cliente prefere à tarde')
        apagar_alheia = gestor.post(f'{base}notas/{nota.pk}/apagar/')
        apagar_propria = atendente.post(f'{base}notas/{nota.pk}/apagar/')

        conversa.refresh_from_db()
        nota.refresh_from_db()
        self.assertEqual(sem_poder.status_code, 409)
        self.assertEqual(conversa.assumida_por, self.outro)
        self.assertEqual(apagar_alheia.status_code, 409)
        self.assertEqual(apagar_propria.status_code, 200)
        self.assertIsNotNone(nota.apagada_em)

    def test_etiquetas_lembrete_e_apelido(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        etiqueta = Etiqueta.objects.create(nome='Quente', cor='VERMELHO')
        web = self.web(self.atendente)
        base = f'/crm/conversas/{conversa.pk}/'

        web.post(f'{base}etiquetas/', {'etiquetas': [etiqueta.pk]})
        web.post(f'{base}lembrete/', {'lembrete_em': _local(timedelta(days=1)), 'texto': 'Ligar'})
        web.post(f'{base}apelido/', {'apelido': 'Dona Maria'})

        conversa.refresh_from_db()
        self.assertEqual(list(conversa.etiquetas.values_list('nome', flat=True)), ['Quente'])
        self.assertEqual((conversa.lembrete_texto, conversa.lembrete_para), ('Ligar', self.atendente))
        self.assertEqual(conversa.nome_exibicao, 'Dona Maria')
        web.post(f'{base}lembrete/concluir/')
        conversa.refresh_from_db()
        self.assertIsNone(conversa.lembrete_em)

    def test_programada_e_resposta_rapida(self):
        conversa = self.conversa_com_humano()
        resposta = RespostaRapida.objects.create(atalho='oi', titulo='Saudação',
                                                 texto='Olá {primeiro_nome}, sou {atendente} da {empresa}.')
        web = self.web(self.atendente)
        base = f'/crm/conversas/{conversa.pk}/'

        cedo = web.post(f'{base}programadas/', {'texto': 'Lembrete', 'enviar_em': _local(timedelta())})
        criada = web.post(f'{base}programadas/', {'texto': 'Lembrete', 'enviar_em': _local(timedelta(hours=2))})
        previa = web.post(f'{base}respostas-rapidas/{resposta.pk}/previa/').json()
        programada = MensagemProgramada.objects.get()
        web.post(f'/crm/programadas/{programada.pk}/cancelar/')

        programada.refresh_from_db()
        self.assertEqual(cedo.status_code, 409)
        self.assertEqual(criada.status_code, 200)
        self.assertEqual(previa['texto'], 'Olá Maria, sou Ana da IPX.')
        self.assertEqual(programada.status, MensagemProgramada.Status.CANCELADA)


class MidiaTests(CrmTestCase):
    def test_imagem_pelo_compositor_e_download_com_log(self):
        conversa = self.conversa_com_humano()
        web = self.web(self.atendente)
        arquivo = SimpleUploadedFile('foto.png', _png(), content_type='image/png')

        with self.captureOnCommitCallbacks(execute=True):
            enviada = web.post(f'/crm/conversas/{conversa.pk}/enviar/', {'arquivo': arquivo, 'texto': 'Veja'})
        mensagem = Mensagem.objects.get(tipo=Mensagem.Tipo.IMAGEM)
        miniatura = web.get(f'/crm/mensagens/{mensagem.pk}/arquivo/', {'versao': 'miniatura'})
        original = web.get(f'/crm/mensagens/{mensagem.pk}/arquivo/')
        sem_acesso = self.web(self.sem_acesso).get(f'/crm/mensagens/{mensagem.pk}/arquivo/')

        self.assertEqual(enviada.status_code, 200)
        self.assertEqual((mensagem.status, mensagem.texto), (Mensagem.Status.ENVIADO, 'Veja'))
        self.assertEqual((miniatura.status_code, original.status_code), (200, 200))
        self.assertEqual(original['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(LogAcessoMidia.objects.count(), 1)  # a miniatura não entra no log
        self.assertEqual(sem_acesso.status_code, 403)
        self.assertContains(web.get(f'/crm/conversas/{conversa.pk}/parte/mensagens/'), 'crm-msg__imagem')

    def test_heic_e_recusado(self):
        conversa = self.conversa_com_humano()
        heic = b'\x00\x00\x00\x18ftypheic' + b'\x00' * 64

        resposta = self.web(self.atendente).post(
            f'/crm/conversas/{conversa.pk}/enviar/', {'arquivo': SimpleUploadedFile('foto.heic', heic)})

        self.assertEqual(resposta.status_code, 409)

    def test_tipos_de_mensagem_renderizam(self):
        conversa = self.conversa_com_humano()
        dados = {
            'LOCALIZACAO': {'localizacao': {'latitude': -1.45, 'longitude': -48.5, 'name': 'Loja', 'address': 'Rua A'}},
            'CONTATO': {'contatos': [{'nome': 'João', 'telefones': [{'numero': '+55 91 9999-0000'}]}]},
            'DESCONHECIDO': {},
        }
        for tipo, extra in dados.items():
            Mensagem.objects.create(conversa=conversa, direcao='ENTRADA', autor='CLIENTE', tipo=tipo, dados=extra)
        Mensagem.objects.create(conversa=conversa, direcao='SAIDA', autor='HUMANO', texto='Falhou', status='ERRO',
                                erro='Número inválido')

        resposta = self.web(self.atendente).get(f'/crm/conversas/{conversa.pk}/parte/mensagens/')

        for trecho in ('Rua A', 'João · +55 91 9999-0000', 'não mostra', 'Número inválido', 'Tentar de novo'):
            with self.subTest(trecho=trecho):
                self.assertContains(resposta, trecho)


class PainelTests(CrmTestCase):
    def _cliente(self, loja, nome='Maria Souza', telefone='(91) 99999-0000'):
        return Cliente.objects.create(
            nome=nome, telefone=telefone, cpf='12345678900', nascimento='1990-01-01', rg='1',
            cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
            comprovantes=ComprovantesCliente.objects.create(loja=loja),
        )

    def _ver_clientes(self):
        self.atendente.user_permissions.add(Permission.objects.get(content_type__app_label='vendas',
                                                                   codename='view_cliente'))
        return self.web(self.criar_usuario_recarregado(self.atendente))

    def test_sugere_e_vincula_cliente_pelo_telefone(self):
        loja = Loja.objects.create(nome='Loja')
        loja.usuarios.add(self.atendente)
        cliente = self._cliente(loja)
        self.receber('Oi', telefone='559199990000')
        conversa = Conversa.objects.get()
        web = self._ver_clientes()
        url = f'/crm/conversas/{conversa.pk}/parte/painel/'

        sugeridos = web.get(url).context['painel']['sugeridos']
        web.post(f'/crm/conversas/{conversa.pk}/vincular-cliente/', {'cliente': cliente.pk})
        painel = web.get(url).context['painel']

        self.assertEqual([s['id'] for s in sugeridos], [cliente.pk])
        self.assertEqual(painel['clientes'][0]['cpf'], '***.456.789-**')
        self.assertEqual(painel['clientes'][0]['vendas'], [])  # sem vendas.view_venda
        self.assertEqual(painel['sugeridos'], [])

    def test_nao_mostra_cliente_de_outra_loja_nem_sem_permissao(self):
        minha, outra = Loja.objects.create(nome='Minha'), Loja.objects.create(nome='Outra')
        minha.usuarios.add(self.atendente)
        cliente_alheio = self._cliente(outra)
        self.receber('Oi', telefone='559199990000')
        conversa = Conversa.objects.get()
        url_vincular = f'/crm/conversas/{conversa.pk}/vincular-cliente/'

        bloqueado = self.web(self.atendente).post(url_vincular, {'cliente': cliente_alheio.pk})
        web = self._ver_clientes()
        sugeridos = web.get(f'/crm/conversas/{conversa.pk}/parte/painel/').context['painel']['sugeridos']
        fora_da_loja = web.post(url_vincular, {'cliente': cliente_alheio.pk})
        busca = web.get(f'/crm/conversas/{conversa.pk}/buscar-cliente/', {'q': 'Maria'}).context['achados']
        conversa.clientes.add(cliente_alheio)  # vinculado por alguém de outra loja
        painel = web.get(f'/crm/conversas/{conversa.pk}/parte/painel/').context['painel']

        self.assertEqual(bloqueado.status_code, 409)
        self.assertEqual(sugeridos, [])
        self.assertEqual(fora_da_loja.status_code, 409)
        self.assertEqual(busca, [])
        self.assertEqual(painel['clientes'], [])


class RevisaoTelasTests(CrmTestCase):
    def test_midia_atende_range_e_registra_o_ip_do_proxy(self):
        conversa = self.conversa_com_humano()
        web = self.web(self.atendente)
        with self.captureOnCommitCallbacks(execute=True):
            web.post(f'/crm/conversas/{conversa.pk}/enviar/',
                     {'arquivo': SimpleUploadedFile('foto.png', _png(), content_type='image/png')})
        mensagem = Mensagem.objects.get(tipo=Mensagem.Tipo.IMAGEM)
        url = f'/crm/mensagens/{mensagem.pk}/arquivo/'

        parcial = web.get(url, HTTP_RANGE='bytes=0-9', HTTP_X_FORWARDED_FOR='1.2.3.4, 10.0.0.5')

        self.assertEqual(parcial.status_code, 206)
        self.assertEqual(len(b''.join(parcial.streaming_content)), 10)
        self.assertTrue(parcial['Content-Range'].startswith('bytes 0-9/'))
        self.assertEqual(LogAcessoMidia.objects.get().ip, '10.0.0.5')

    def test_resolver_e_devolver_recusado_nao_muda_a_situacao(self):
        conversa = self.conversa_com_humano(self.outro)

        resposta = self.web(self.atendente).post(f'/crm/conversas/{conversa.pk}/situacao/',
                                                 {'situacao': 'RESOLVIDA', 'devolver_automatico': '1'})

        conversa.refresh_from_db()
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual((conversa.situacao, conversa.modo), ('ABERTA', 'HUMANO'))

    def test_etiqueta_com_digito_unicode_nao_quebra(self):
        self.assertEqual(self.web(self.atendente).get('/crm/', {'etiqueta': '²'}).status_code, 200)

    def test_nova_conversa_lista_aberturas_mesmo_sem_conversa_aberta(self):
        self.abertura_aprovada('Retomar contato', 'Olá {nome}, podemos continuar seu atendimento?')

        resposta = self.web(self.atendente, ajax=False).get('/crm/')

        self.assertContains(resposta, 'Retomar contato')
        self.assertContains(resposta, 'Modo simulado')

    def test_mensagens_antigas_mantem_responder(self):
        conversa = self.conversa_com_humano()

        resposta = self.web(self.atendente).get(f'/crm/conversas/{conversa.pk}/mensagens/')

        self.assertContains(resposta, 'data-crm-responder')
