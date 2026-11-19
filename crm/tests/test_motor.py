from datetime import timedelta
from unittest import mock

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, Mensagem, Nota
from crm.services import conversas
from crm.services.conversas import ConflitoCRM
from crm.tests.base import CrmTestCase, fechar_janela


class AtendimentoAutomaticoTests(CrmTestCase):
    def test_mensagem_nova_recebe_boas_vindas_e_vai_para_a_fila(self):
        self.receber('Oi, quero um celular')

        conversa = Conversa.objects.get()
        boas_vindas = Mensagem.objects.filter(origem=Mensagem.Origem.BOAS_VINDAS)
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertEqual(conversa.situacao, Conversa.Situacao.ABERTA)
        self.assertEqual(conversa.nao_lidas, 1)
        self.assertEqual(boas_vindas.count(), 1)
        self.assertEqual(boas_vindas.get().autor, Mensagem.Autor.AUTOMATICO)
        self.assertTrue(Nota.objects.filter(conversa=conversa, tipo=Nota.Tipo.TRANSFERENCIA).exists())
        self.assertTrue(Mensagem.objects.filter(direcao=Mensagem.Direcao.ENTRADA, processada=True).exists())

    def test_boas_vindas_nao_se_repete_em_24h(self):
        self.receber('Oi')
        conversas.devolver(Conversa.objects.get(), automatico=True)
        self.receber('Oi de novo')

        self.assertEqual(Mensagem.objects.filter(origem=Mensagem.Origem.BOAS_VINDAS).count(), 1)

    def test_boas_vindas_desligada_transfere_em_silencio(self):
        ConfiguracaoCRM.objects.update_or_create(pk=1, defaults={'boas_vindas_ativa': False})

        self.receber('Oi')

        self.assertFalse(Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).exists())
        self.assertTrue(Nota.objects.get(tipo=Nota.Tipo.TRANSFERENCIA).silenciosa)

    def test_conversa_com_humano_nao_recebe_resposta_automatica(self):
        conversa = self.conversa_com_humano()
        saidas_antes = Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).count()

        self.receber('Mais uma pergunta')

        conversa.refresh_from_db()
        self.assertEqual(conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).count(), saidas_antes)

    def test_wa_id_sem_nono_digito_usa_a_mesma_conversa(self):
        self.receber('Primeira', telefone='5591999990000')
        self.receber('Segunda', telefone='559199990000')

        self.assertEqual(Conversa.objects.count(), 1)
        self.assertEqual(Conversa.objects.get().telefone, '559199990000')

    def test_reacao_nao_reabre_janela_nem_conta_como_nao_lida(self):
        conversa = self.conversa_com_humano()
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)

        self.receber('', tipo='REACAO', dados={'reacao': {'emoji': '👍', 'alvo_wa_id': 'x'}})

        conversa.refresh_from_db()
        self.assertEqual(conversa.nao_lidas, 0)

    def test_falha_da_meta_vira_erro_legivel_e_conversa_segue(self):
        from crm.whatsapp import ErroWhatsApp

        with mock.patch('crm.whatsapp.ProviderSimulado.enviar_texto', side_effect=ErroWhatsApp('Fora do ar', 131026)):
            self.receber('Oi')

        boas_vindas = Mensagem.objects.get(origem=Mensagem.Origem.BOAS_VINDAS)
        self.assertEqual(boas_vindas.status, Mensagem.Status.ERRO)
        self.assertEqual(Conversa.objects.get().modo, Conversa.Modo.AGUARDANDO)


class PosseETravaTests(CrmTestCase):
    def test_assumir_conversa_de_outro_da_conflito(self):
        conversa = self.conversa_com_humano(self.outro)

        with self.assertRaises(ConflitoCRM):
            conversas.assumir(conversa, self.atendente)

    def test_puxar_confere_o_dono_atual(self):
        conversa = self.conversa_com_humano(self.outro)

        with self.assertRaises(ConflitoCRM):
            conversas.puxar(conversa, self.atendente, de_usuario_id=self.gestor.pk)
        conversas.puxar(conversa, self.atendente, de_usuario_id=self.outro.pk)

        conversa.refresh_from_db()
        self.assertEqual(conversa.assumida_por, self.atendente)
        self.assertTrue(Nota.objects.filter(conversa=conversa, texto__icontains='puxou').exists())

    def test_trava_de_resposta(self):
        conversa = self.conversa_com_humano(self.outro)
        bloqueio_outro_dono = conversas.bloqueio_de(conversa, self.atendente)
        conversas.devolver(conversa, self.outro)
        conversa.refresh_from_db()
        bloqueio_nao_assumida = conversas.bloqueio_de(conversa, self.atendente)
        conversa = conversas.assumir(conversa, self.atendente)
        fechar_janela(conversa)
        bloqueio_janela = conversas.bloqueio_de(conversa, self.atendente)

        self.assertEqual(bloqueio_outro_dono['motivo'], 'OUTRO_DONO')
        self.assertEqual(bloqueio_nao_assumida['motivo'], 'NAO_ASSUMIDA')
        self.assertEqual(bloqueio_janela['motivo'], 'JANELA_FECHADA')

    def test_devolver_de_outro_dono_exige_gerenciar(self):
        conversa = self.conversa_com_humano(self.outro)

        with self.assertRaises(ConflitoCRM):
            conversas.devolver(conversa, self.atendente)
        conversas.devolver(conversa, self.gestor, pode_gerenciar=True)

        conversa.refresh_from_db()
        self.assertEqual(conversa.modo, Conversa.Modo.AUTOMATICO)

    def test_retorno_automatico_so_para_resolvida_e_parada(self):
        conversa = self.conversa_com_humano()
        antigo = timezone.now() - timedelta(hours=30)
        Conversa.objects.filter(pk=conversa.pk).update(
            situacao=Conversa.Situacao.RESOLVIDA, situacao_em=antigo, assumida_em=antigo, ultima_humana_em=antigo,
        )
        conversa.refresh_from_db()

        voltou = conversas.avaliar_retorno_automatico(conversa)

        conversa.refresh_from_db()
        self.assertTrue(voltou)
        self.assertEqual(conversa.modo, Conversa.Modo.AUTOMATICO)
