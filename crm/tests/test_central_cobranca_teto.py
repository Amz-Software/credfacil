"""Revisão da Central de cobrança: teto em janela móvel de 24 h e atômico por envio, pausa de segurança
sem leitura da Meta, reserva da régua, reserva de itens, cancelamento no meio, versão e idade do disparo."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from crm.models import ConfiguracaoCRM, DisparoCobranca, ItemDisparo, Mensagem, TentativaContato
from crm.services import cobranca
from crm.services.central_cobranca import agenda, disparos, envio_disparos, teto
from crm.services.central_cobranca.motivos import Motivo
from crm.services.conversas import ConflitoCRM
from crm.tests.test_central_cobranca import provider_com_numero, saude
from crm.tests.test_disparos_cobranca import DisparoBase
from crm.whatsapp import ErroWhatsApp
from vendas.models import Parcela

Status = DisparoCobranca.Status
Situacao = ItemDisparo.Situacao
Tipo = TentativaContato.Tipo


class JanelaMovelTests(DisparoBase):
    def mensagem_ha(self, horas: float) -> Mensagem:
        from crm.models import Conversa

        conversa = Conversa.objects.get_or_create(telefone='5591900000000')[0]
        mensagem = Mensagem.objects.create(conversa=conversa, direcao=Mensagem.Direcao.SAIDA,
                                           autor=Mensagem.Autor.AUTOMATICO, origem=Mensagem.Origem.COBRANCA,
                                           status=Mensagem.Status.ENVIADO, texto='aviso')
        Mensagem.objects.filter(pk=mensagem.pk).update(criado_em=timezone.now() - timedelta(hours=horas))
        return mensagem

    def test_conta_as_ultimas_24_horas_e_nao_o_dia(self):
        self.mensagem_ha(20)  # "ontem à noite"
        self.mensagem_ha(25)  # fora da janela

        self.assertEqual(teto.enviados_24h(), 1)
        self.assertEqual(teto.restante(saude(teto_configurado=3)), 2)

    def test_envio_confere_o_teto_dentro_da_transacao(self):
        self.mensagem_ha(1)
        versao = cobranca.versao_vigente(ConfiguracaoCRM.obter(), 'modelo_aviso_apos')

        with self.assertRaises(teto.TetoAtingido):
            cobranca.enviar_aviso(versao, self.atrasada, Tipo.DISPARO, 99, limite=1)

        self.assertFalse(TentativaContato.objects.exists())

    def test_segundo_remetente_e_recusado_quando_o_teto_enche(self):
        """Régua e disparo leram o mesmo 'restante' antes: só o primeiro envio cabe."""
        _, outra = self.outro_cliente(1, -7)
        versao = cobranca.versao_vigente(ConfiguracaoCRM.obter(), 'modelo_aviso_apos')
        with self.captureOnCommitCallbacks(execute=True):
            primeiro = cobranca.enviar_aviso(versao, self.atrasada, Tipo.DISPARO, 98, limite=1)
            with self.assertRaises(teto.TetoAtingido):
                cobranca.enviar_aviso(versao, outra, Tipo.DISPARO, 98, limite=1)

        self.assertIsNotNone(primeiro)
        self.assertEqual(TentativaContato.objects.count(), 1)

    def test_rodada_para_quando_outro_processo_ocupa_a_vaga(self):
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=1)
        Parcela.objects.filter(pk=self.atrasada.pk).update(pago=True)
        self.vencer_em(self.parcelas[0], 0)
        Parcela.objects.filter(pk=self.parcelas[0].pk).update(pago=False)
        self.outro_cliente(1, 0)
        with mock.patch.object(teto, 'restante', return_value=5):  # leu antes do outro processo enviar
            self.mensagem_ha(1)
            self.assertEqual(self.rodar(), {})
        self.assertFalse(TentativaContato.objects.exists())


class LeituraDaMetaTests(DisparoBase):
    def ler_com_falha(self, ha_horas: float | None):
        lido = timezone.now() - timedelta(hours=ha_horas) if ha_horas is not None else None
        ConfiguracaoCRM.objects.filter(pk=1).update(meta_limite='TIER_2K', meta_qualidade='GREEN', meta_lido_em=lido)
        teto.limpar_cache()
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero(erro=ErroWhatsApp('fora'))), \
                self.assertLogs(teto.logger, 'WARNING'):
            return teto.ler_saude(ConfiguracaoCRM.obter())

    def test_falha_com_leitura_recente_nao_pausa(self):
        estado = self.ler_com_falha(0.2)

        self.assertEqual((estado.pausada, estado.teto_efetivo, estado.fonte), (False, 1600, teto.Fonte.ULTIMA_LEITURA))

    def test_falha_com_leitura_velha_ou_sem_leitura_pausa_por_seguranca(self):
        for horas in (2, None):
            with self.subTest(horas=horas):
                estado = self.ler_com_falha(horas)
                self.assertEqual(estado.motivo_pausa, teto.PAUSA_SEM_LEITURA)

    def test_regua_pausada_ainda_roda_os_alertas(self):
        self.ler_com_falha(2)
        with mock.patch.object(cobranca._Rodada, 'alertas') as alertas, \
                mock.patch.object(cobranca._Rodada, 'etapas') as etapas:
            self.assertEqual(self.rodar(), {})
        alertas.assert_called_once()
        etapas.assert_not_called()

    def test_disparo_nao_sai_sem_leitura_recente(self):
        disparo = self.agendado()
        self.ler_com_falha(2)

        self.assertEqual(self.processar(), {})
        self.assertEqual(disparos.situacao_envio(ConfiguracaoCRM.obter(), teto.ler_saude(), self.agora()),
                         Motivo.SEM_LEITURA_RECENTE)
        self.assertEqual(DisparoCobranca.objects.get(pk=disparo.pk).enviados, 0)

    def agora(self):
        from crm.tests.test_cobranca import momento

        return momento(self.hoje, 10)


class ReservaDaReguaTests(DisparoBase):
    def test_disparo_nao_come_a_vaga_da_regua_de_hoje(self):
        self.outro_cliente(5, 3)  # a régua manda "antes" hoje para outro cliente
        self.outro_cliente(1, -7)
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=2)
        disparo = self.agendado()

        reserva = agenda.reserva_da_regua(ConfiguracaoCRM.obter(), teto.ler_saude(), self.momento_teste())

        self.assertEqual(reserva[self.hoje], 1)
        self.assertEqual(self.processar(), {disparo.pk: 1})
        self.assertEqual(self.rodar(), {Tipo.AVISO_ANTES: 1})

    def test_distribuicao_desconta_a_reserva(self):
        config = ConfiguracaoCRM.obter()
        amanha = self.hoje + timedelta(days=1)
        dias, _ = disparos.distribuicao(10, config, saude(teto_configurado=5), self.momento_teste(),
                                        reserva={self.hoje: 4, amanha: 5})

        self.assertEqual(dias[0], (self.hoje, 1))
        self.assertNotIn(amanha, [dia for dia, _ in dias])

    def momento_teste(self):
        from crm.tests.test_cobranca import momento

        return momento(self.hoje, 10)


class ItensEDisparoTests(DisparoBase):
    def test_item_reservado_nao_e_processado_duas_vezes(self):
        disparo = self.agendado()
        item = disparo.itens.get(situacao=Situacao.PENDENTE)

        self.assertTrue(envio_disparos._reservar_item(item))
        self.assertFalse(envio_disparos._reservar_item(item))
        self.assertEqual(self.processar(), {disparo.pk: 0})  # a única vaga está com "outro processo"

    def test_reserva_esquecida_volta_para_a_fila_ou_vira_enviado(self):
        _, outra = self.outro_cliente(1, -7)
        disparo = self.agendado()
        perdido, enviado = disparo.itens.filter(situacao=Situacao.PENDENTE).order_by('ordem')
        velho = timezone.now() - timedelta(minutes=30)
        ItemDisparo.objects.filter(pk__in=[perdido.pk, enviado.pk]).update(situacao=Situacao.ENVIANDO,
                                                                         processado_em=velho)
        TentativaContato.objects.create(cliente_id=enviado.cliente_id, numero='91988880001', tipo=Tipo.DISPARO,
                                        parcela_id=enviado.parcela_id, sequencia=disparo.pk)

        self.assertEqual(envio_disparos.recuperar_reservas_esquecidas(), 2)

        situacoes = dict(disparo.itens.values_list('pk', 'situacao'))
        self.assertEqual((situacoes[perdido.pk], situacoes[enviado.pk]), (Situacao.PENDENTE, Situacao.ENVIADO))
        self.assertIsNotNone(outra)

    def test_cancelado_durante_o_envio_para_e_nao_vira_pausado(self):
        for numero in range(1, 4):
            self.outro_cliente(numero, -7)
        disparo = self.agendado()
        original = cobranca.enviar_aviso

        def enviar_e_cancelar(*args, **kwargs):
            disparos.cancelar(disparo, self.gestor)
            return original(*args, **kwargs)

        with mock.patch.object(cobranca, 'enviar_aviso', side_effect=enviar_e_cancelar):
            self.assertEqual(self.processar(), {disparo.pk: 1})
        envio_disparos._pausar(disparo, 'teste')

        disparo.refresh_from_db()
        self.assertEqual((disparo.status, disparo.enviados), (Status.CANCELADO, 1))

    def test_mensagem_trocada_depois_da_previa_pausa_e_nao_retoma(self):
        disparo = self.agendado()
        versao = disparo.versao
        nova = type(versao).objects.create(modelo=versao.modelo, versao=versao.versao + 1, nome_meta='nova_v2',
                                           corpo=versao.corpo, corpo_meta=versao.corpo_meta,
                                           mapa_parametros=versao.mapa_parametros, status=versao.status, vigente=True)
        type(versao).objects.filter(pk=versao.pk).update(vigente=False)

        self.processar()

        disparo.refresh_from_db()
        self.assertEqual(disparo.status, Status.PAUSADO)
        with self.assertRaises(ConflitoCRM):
            disparos.retomar(disparo)
        self.assertIsNotNone(nova.pk)

    def test_disparo_com_mais_de_3_dias_expira(self):
        disparo = self.agendado()
        DisparoCobranca.objects.filter(pk=disparo.pk).update(confirmado_em=timezone.now() - timedelta(days=4))

        self.processar()

        disparo.refresh_from_db()
        self.assertEqual((disparo.status, disparo.ignorados, disparo.enviados), (Status.CONCLUIDO, 1, 0))
        self.assertEqual(disparo.itens.get().motivo, Motivo.DISPARO_EXPIRADO)
        DisparoCobranca.objects.filter(pk=disparo.pk).update(status=Status.PAUSADO)
        with self.assertRaises(ConflitoCRM):
            disparos.retomar(DisparoCobranca.objects.get(pk=disparo.pk))

    def test_motivo_especifico_quando_nada_sai(self):
        disparo = self.agendado()
        with mock.patch.object(cobranca, 'enviar_aviso', return_value=None):
            self.processar()

        self.assertEqual(disparo.itens.get().motivo, Motivo.NAO_ENVIADO)
