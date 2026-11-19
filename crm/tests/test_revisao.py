"""Regressões dos achados da revisão de código do CRM."""
import io
import json
import os
import tempfile
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from crm.models import Conversa, Mensagem, MensagemProgramada, ModeloAbertura, Nota
from crm.services import aberturas, conversas, midias, organizacao
from crm.services.conversas import ConflitoCRM, EntradaNormalizada, receber_mensagem
from crm.tests.base import CrmTestCase, fechar_janela
from crm.whatsapp import ErroWhatsApp


def _png() -> bytes:
    from PIL import Image

    saida = io.BytesIO()
    Image.new('RGB', (60, 40), 'blue').save(saida, format='PNG')
    return saida.getvalue()


class WebhookRobustoTests(CrmTestCase):
    @override_settings(DEBUG=True)
    def test_assinatura_com_texto_nao_ascii_e_recusada_sem_500(self):
        with mock.patch.dict(os.environ, {'WHATSAPP_APP_SECRET': 'SEGREDO-XYZ', 'WHATSAPP_VERIFY_TOKEN': 'tok'}):
            post = self.client.post('/api/whatsapp/webhook/', b'{}', content_type='application/json',
                                    HTTP_X_HUB_SIGNATURE_256='sha256=é')
            get = self.client.get('/api/whatsapp/webhook/', {'hub.mode': 'subscribe', 'hub.verify_token': 'é',
                                                             'hub.challenge': '1'})

        self.assertEqual((post.status_code, get.status_code), (403, 403))
        self.assertNotIn(b'SEGREDO-XYZ', post.content + get.content)

    def test_credenciais_nao_aparecem_no_repr(self):
        from crm.whatsapp import credenciais

        with mock.patch.dict(os.environ, {'WHATSAPP_TOKEN': 'TOKEN-SECRETO', 'WHATSAPP_APP_SECRET': 'APP-SECRETO'}):
            texto = repr(credenciais())

        self.assertNotIn('TOKEN-SECRETO', texto)
        self.assertNotIn('APP-SECRETO', texto)


class AberturaAntispamTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        modelo = aberturas.criar_modelo('Retomar', 'Olá {nome}, podemos continuar o atendimento?', self.gestor)
        aberturas.simular_decisao(modelo, 'APROVADO')
        self.chave = modelo.chave

    def test_segunda_abertura_sem_resposta_e_bloqueada(self):
        conversa = self.conversa_com_humano()
        fechar_janela(conversa)
        aberturas.enviar_abertura(conversa, self.atendente, self.chave)

        with self.assertRaises(ConflitoCRM):
            aberturas.enviar_abertura(Conversa.objects.get(pk=conversa.pk), self.atendente, self.chave)
        self.assertEqual(Mensagem.objects.filter(origem=Mensagem.Origem.ABERTURA).count(), 1)

    def test_abertura_com_erro_e_reenviada_como_template(self):
        from crm.services import envio

        conversa = self.conversa_com_humano()
        fechar_janela(conversa)
        with mock.patch('crm.whatsapp.ProviderSimulado.enviar_template', side_effect=ErroWhatsApp('Falhou', 131042)):
            with self.assertRaises(ConflitoCRM):
                aberturas.enviar_abertura(conversa, self.atendente, self.chave)
        falha = Mensagem.objects.get(origem=Mensagem.Origem.ABERTURA)

        with mock.patch('crm.whatsapp.ProviderSimulado.enviar_template', return_value='wamid.ok') as template:
            reenviada = envio.reenviar(falha, self.atendente)

        self.assertEqual(reenviada.status, Mensagem.Status.ENVIADO)
        template.assert_called_once()
        self.assertEqual(template.call_args.args[1], falha.dados['abertura']['versao'])

    def test_abertura_invalida_nao_assume_a_conversa(self):
        self.receber('Oi')
        conversa = Conversa.objects.get()
        fechar_janela(conversa)

        with self.assertRaises(ConflitoCRM):
            aberturas.enviar_abertura(conversa, self.atendente, 'nao-existe')

        conversa.refresh_from_db()
        self.assertNotEqual(conversa.modo, Conversa.Modo.HUMANO)

    def test_edicao_invalida_nao_grava_nada(self):
        modelo = ModeloAbertura.objects.get(chave=self.chave)

        with self.assertRaises(ConflitoCRM):
            aberturas.editar_modelo(modelo, {'titulo': 'Título novo', 'corpo': '{nome}'}, self.gestor)
        with self.assertRaises(ConflitoCRM):
            aberturas.editar_modelo(modelo, {'titulo': 'x'}, self.gestor)

        modelo.refresh_from_db()
        self.assertEqual(modelo.titulo, 'Retomar')


class MotorResilienteTests(CrmTestCase):
    def test_mensagem_com_defeito_nao_trava_e_vai_para_a_equipe(self):
        with mock.patch('crm.services.conversas.atendimento_automatico', side_effect=RuntimeError('quebrou')):
            self.receber('Oi')

        conversa = Conversa.objects.get()
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertFalse(Mensagem.objects.filter(direcao=Mensagem.Direcao.ENTRADA, processada=False).exists())
        self.assertTrue(Nota.objects.filter(conversa=conversa, texto__icontains='Erro ao processar').exists())

    def test_transferir_nao_tira_a_conversa_de_quem_assumiu(self):
        conversa = self.conversa_com_humano()

        transferiu = conversas.transferir(conversa, 'tarde demais')

        conversa.refresh_from_db()
        self.assertFalse(transferiu)
        self.assertEqual((conversa.modo, conversa.assumida_por), (Conversa.Modo.HUMANO, self.atendente))

    def test_entrega_atrasada_nao_encolhe_a_janela(self):
        conversa = self.conversa_com_humano()
        antes = Conversa.objects.get(pk=conversa.pk).ultima_entrada_em

        with self.captureOnCommitCallbacks(execute=True):
            receber_mensagem(EntradaNormalizada(telefone=conversa.telefone, wa_message_id='wamid.antiga',
                                                tipo='TEXTO', texto='atrasada',
                                                criado_em=timezone.now() - timedelta(hours=20)))

        self.assertEqual(Conversa.objects.get(pk=conversa.pk).ultima_entrada_em, antes)


class MidiaRecebidaTests(CrmTestCase):
    def test_baixa_em_storage_privado_com_miniatura(self):
        conteudo = _png()
        temporario = tempfile.NamedTemporaryFile(delete=False)
        temporario.write(conteudo)
        temporario.close()
        self.receber('', tipo='IMAGEM', midia_id='media.1', midia_meta={'mime': 'image/png'})
        midia = Mensagem.objects.get(tipo=Mensagem.Tipo.IMAGEM).midia

        with mock.patch('crm.whatsapp.ProviderSimulado.baixar_midia', return_value=(temporario.name, 'image/png', '')):
            midias.baixar(midia)

        midia.refresh_from_db()
        self.assertEqual(midia.status, midia.Status.OK)
        self.assertEqual((midia.largura, midia.altura, midia.tamanho_bytes), (60, 40, len(conteudo)))
        self.assertTrue(midia.miniatura)
        self.assertTrue(os.path.realpath(midia.arquivo.path).startswith(os.path.realpath(settings.CRM_MIDIA_ROOT)))
        self.assertIsNone(midia.arquivo.storage.base_url)
        self.assertFalse(os.path.exists(temporario.name))

    def test_sha_divergente_vira_erro(self):
        temporario = tempfile.NamedTemporaryFile(delete=False)
        temporario.write(b'abc')
        temporario.close()
        self.receber('', tipo='DOCUMENTO', midia_id='media.2', midia_meta={'mime': 'application/pdf', 'sha256': 'x'})
        midia = Mensagem.objects.get(tipo=Mensagem.Tipo.DOCUMENTO).midia

        with mock.patch('crm.whatsapp.ProviderSimulado.baixar_midia', return_value=(temporario.name, 'application/pdf', '')):
            midias.baixar(midia)

        midia.refresh_from_db()
        self.assertEqual(midia.status, midia.Status.ERRO)


class ProgramadaTravadaTests(CrmTestCase):
    def test_enviando_parada_vira_erro_com_nota(self):
        conversa = self.conversa_com_humano()
        programada = MensagemProgramada.objects.create(
            conversa=conversa, criado_por=self.atendente, texto='x', status=MensagemProgramada.Status.ENVIANDO,
            enviar_em=timezone.now() - timedelta(minutes=30),
        )

        recuperadas = organizacao.recuperar_programadas_travadas()

        programada.refresh_from_db()
        self.assertEqual(recuperadas, 1)
        self.assertEqual(programada.status, MensagemProgramada.Status.ERRO)


class ListaSemDistinctTests(CrmTestCase):
    def test_busca_e_ordem_por_espera_juntas(self):
        self.receber('Quero um iPhone', telefone='5591911112222')
        self.receber('Quero um iPhone também', telefone='5591933334444')

        resposta = self.web(self.atendente).get('/crm/lista/', {'fila': 'todas', 'q': 'iphone', 'ordem': 'espera'})

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context['conversas']), 2)

    def test_parametros_invalidos_nao_quebram(self):
        conversa = self.conversa_com_humano()
        web = self.web(self.atendente)

        antigas = web.get(f'/crm/conversas/{conversa.pk}/mensagens/', {'antes': 'abc'})
        lista = web.get('/crm/lista/', {'fila': 'xyz', 'etiqueta': '-1', 'ordem': 'nada', 'atual': 'x'})

        self.assertEqual(antigas.status_code, 200)
        self.assertEqual(lista.status_code, 200)
        self.assertEqual(lista.context['filtros'].fila, 'minhas')
