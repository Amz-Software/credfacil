"""Central de cobrança (serviços): teto diário, pausa por qualidade, agenda da régua e histórico."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Mensagem, TelefoneCliente, TentativaContato
from crm.services import cobranca, contatos
from crm.services.central_cobranca import agenda, historico, janela, teto
from crm.services.central_cobranca.motivos import Motivo, mascarar
from crm.services.envio import aplicar_status
from crm.tests.fabrica_cobranca import criar_cliente, criar_parcelas
from crm.tests.test_cobranca import ReguaBase, momento
from crm.whatsapp import ErroWhatsApp
from vendas.models import ContatoAdicional, Parcela

Tipo = TentativaContato.Tipo


def saude(qualidade: str = '', tier: str = 'TIER_250', teto_configurado: int | None = None) -> teto.SaudeNumero:
    return teto.SaudeNumero(limite_tier=tier, qualidade=qualidade, fonte=teto.Fonte.META, lido_em=None,
                            teto_configurado=teto_configurado)


def provider_com_numero(limite: str = 'TIER_2K', qualidade: str = 'GREEN', erro: Exception | None = None):
    consultar = mock.Mock(side_effect=erro) if erro else mock.Mock(return_value={'limite': limite,
                                                                               'qualidade': qualidade})
    return mock.Mock(consultar_numero=consultar)


class CentralBase(ReguaBase):
    def setUp(self):
        super().setUp()
        teto.limpar_cache()
        self.addCleanup(teto.limpar_cache)
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)  # sem atraso antigo no cenário

    def outro_cliente(self, numero: int, vencimento_em: int, telefone: str | None = None):
        cliente = criar_cliente(self.loja, f'Cliente {numero}', telefone or f'9198888{numero:04d}', f'{numero:011d}')
        parcela = criar_parcelas(cliente, self.atendente, [self.hoje + timedelta(days=vencimento_em)])[0]
        return cliente, parcela

    def config(self) -> ConfiguracaoCRM:
        return ConfiguracaoCRM.obter()

    def projetar(self, dias: int = 0, estado: teto.SaudeNumero | None = None, hora: int = 10):
        return agenda.projetar(self.config(), estado or saude(), dias, agora=momento(self.hoje, hora))


class TetoTests(CentralBase):
    def test_teto_e_80_por_cento_do_limite_da_meta_e_o_configurado_so_baixa(self):
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero('TIER_2K')):
            lida = teto.ler_saude(self.config(), forcar=True)
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=100)
        baixado = teto.ler_saude(self.config())
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=5000)
        acima = teto.ler_saude(self.config())

        self.assertEqual((lida.teto_automatico, lida.teto_efetivo, lida.fonte), (1600, 1600, teto.Fonte.META))
        self.assertEqual(baixado.teto_efetivo, 100)
        self.assertEqual(acima.teto_efetivo, 1600)
        self.assertEqual((self.config().meta_limite, self.config().meta_qualidade), ('TIER_2K', 'GREEN'))

    def test_leitura_fica_no_cache_e_falha_da_meta_usa_a_ultima_leitura(self):
        provider = provider_com_numero('TIER_10K')
        with mock.patch.object(teto, 'obter_provider', return_value=provider):
            teto.ler_saude(self.config(), forcar=True)
            teto.ler_saude(self.config())
        self.assertEqual(provider.consultar_numero.call_count, 1)

        teto.limpar_cache()
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero(erro=ErroWhatsApp('fora'))):
            reserva = teto.ler_saude(self.config())
        self.assertEqual((reserva.teto_efetivo, reserva.fonte), (8000, teto.Fonte.ULTIMA_LEITURA))

    def test_sem_meta_e_sem_leitura_anterior_vale_o_padrao(self):
        estado = teto.ler_saude(self.config(), forcar=True)  # modo simulado

        self.assertEqual((estado.teto_efetivo, estado.fonte, estado.pausada_por_qualidade),
                         (teto.TETO_PADRAO, teto.Fonte.PADRAO, False))

    def test_cache_fora_do_ar_nao_para_nada(self):
        with mock.patch.object(teto, '_cache', side_effect=RuntimeError('redis')), \
                self.assertLogs(teto.logger, 'WARNING'):
            self.assertEqual(teto.ler_saude(self.config()).teto_efetivo, teto.TETO_PADRAO)

    def test_conta_templates_da_empresa_no_dia_sem_os_recusados(self):
        self.vencer_em(self.parcelas[2], 3)
        self.rodar()
        conversa = Mensagem.objects.get(origem=Mensagem.Origem.COBRANCA).conversa
        for origem, status in ((Mensagem.Origem.ABERTURA, Mensagem.Status.ENVIADO),
                               (Mensagem.Origem.COMPRA, Mensagem.Status.ERRO), ('', Mensagem.Status.ENVIADO)):
            Mensagem.objects.create(conversa=conversa, direcao=Mensagem.Direcao.SAIDA, autor=Mensagem.Autor.HUMANO,
                                    origem=origem, status=status, texto='x')

        self.assertEqual(teto.enviados_no_dia(timezone.localdate()), 2)

    def test_regua_para_no_teto_do_dia(self):
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=1)
        self.vencer_em(self.parcelas[2], 0)
        self.outro_cliente(1, 0)

        self.assertEqual(self.rodar(), {Tipo.AVISO_DIA: 1})
        self.assertEqual(self.rodar(), {})

    def test_qualidade_amarela_ou_vermelha_pausa_a_regua(self):
        self.vencer_em(self.parcelas[2], 3)
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero('TIER_2K', 'YELLOW')):
            self.assertEqual(self.rodar(), {})
        self.assertFalse(Mensagem.objects.filter(origem=Mensagem.Origem.COBRANCA).exists())

        teto.limpar_cache()
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero('TIER_2K', 'GREEN')):
            self.assertEqual(self.rodar(), {Tipo.AVISO_ANTES: 1})


class JanelaTests(CentralBase):
    def test_proxima_janela_e_minutos_restantes(self):
        config = self.config()
        cedo = janela.proxima(config, momento(self.hoje, 7))
        tarde = janela.proxima(config, momento(self.hoje, 21))

        self.assertEqual(timezone.localtime(cedo.inicio).date(), self.hoje)
        self.assertGreater(timezone.localtime(tarde.inicio).date(), self.hoje)
        self.assertEqual(janela.minutos_no_dia(config, self.hoje, momento(self.hoje, 19)), 60)
        self.assertEqual(mascarar('5591999990000'), '(91) *****-0000')
        self.assertEqual(mascarar('123'), '')


class AgendaTests(CentralBase):
    def previstos(self, dia: agenda.DiaAgenda) -> set[tuple[int, str]]:
        return {(item.parcela.pk, item.etapa) for item in dia.itens if item.previsto}

    def motivos(self, dia: agenda.DiaAgenda) -> dict[int, str]:
        return {item.parcela.pk: item.motivo for item in dia.itens if item.motivo}

    def test_previa_de_hoje_e_exatamente_o_que_a_rotina_envia(self):
        antes = self.vencer_em(self.parcelas[2], 3)
        _, do_dia = self.outro_cliente(1, 0)
        referencia, so_ref = self.outro_cliente(2, 3)
        referencia.contato_adicional = ContatoAdicional.objects.create(nome_adicional='João', contato='91977770000')
        referencia.save()
        contatos.mudar_situacao(contatos.para_aviso(referencia), TelefoneCliente.Situacao.SEM_WHATSAPP)
        _, informada = self.outro_cliente(3, 0)
        Parcela.objects.filter(pk=informada.pk).update(pagamento_efetuado=True)

        hoje = self.projetar()[0]
        self.rodar()

        enviados = {(t.parcela_id, agenda.CHAVES[t.tipo]) for t in TentativaContato.objects.all()}
        self.assertEqual(self.previstos(hoje), {(antes.pk, 'antes'), (do_dia.pk, 'dia')})
        self.assertEqual(enviados, self.previstos(hoje))
        self.assertEqual(self.motivos(hoje),
                         {so_ref.pk: Motivo.SO_REFERENCIA, informada.pk: Motivo.PAGAMENTO_INFORMADO})
        self.assertFalse(Mensagem.objects.filter(conversa__telefone__endswith='77770000').exists())

    def test_um_aviso_por_cliente_por_dia_e_teto(self):
        self.vencer_em(self.parcelas[0], 0)
        Parcela.objects.filter(pk=self.parcelas[0].pk).update(pago=False)
        self.vencer_em(self.parcelas[2], 3)
        _, outra = self.outro_cliente(1, 0)

        dia = self.projetar(estado=saude(teto_configurado=1))[0]

        # Mesma ordem da rotina: "antes" vem antes de "no dia".
        self.assertEqual(self.previstos(dia), {(self.parcelas[2].pk, 'antes')})
        self.assertEqual(self.motivos(dia),
                         {self.parcelas[0].pk: Motivo.JA_AVISADO_HOJE, outra.pk: Motivo.LIMITE_DIARIO})

    def test_bloqueios_do_dia(self):
        self.vencer_em(self.parcelas[2], 3)
        casos = [
            ({'cobranca_ativa': False}, saude(), Motivo.REGUA_PAUSADA),
            ({'cobranca_ativada_em': momento(self.hoje + timedelta(days=2), 0)}, saude(), Motivo.ANTES_DA_ATIVACAO),
            ({}, saude('RED'), Motivo.PAUSADA_POR_QUALIDADE),
        ]
        for campos, estado, motivo in casos:
            with self.subTest(motivo=motivo):
                ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_ativa=True,
                                                            cobranca_ativada_em=timezone.now() - timedelta(days=1))
                ConfiguracaoCRM.objects.filter(pk=1).update(**campos)
                dia = self.projetar(estado=estado)[0]
                self.assertEqual(dia.bloqueio, motivo)
                self.assertEqual(self.previstos(dia), set())
        self.assertEqual(self.projetar(hora=21)[0].bloqueio, Motivo.FORA_DO_HORARIO)

    def test_bom_pagador_e_etapa_sem_modelo(self):
        parcela = self.vencer_em(self.parcelas[2], 3)
        with mock.patch.object(agenda, 'bons_pagadores', return_value={self.cliente.pk}):
            self.assertEqual(self.motivos(self.projetar()[0]), {parcela.pk: Motivo.BOM_PAGADOR})

        ConfiguracaoCRM.objects.filter(pk=1).update(modelo_aviso_antes=None)
        self.assertEqual(self.motivos(self.projetar()[0]), {parcela.pk: Motivo.ETAPA_SEM_MODELO})

    def test_domingo_passa_o_aviso_para_o_proximo_dia_de_envio(self):
        domingo = self.hoje + timedelta(days=(6 - self.hoje.weekday()) % 7 or 7)
        parcela = self.vencer_em(self.parcelas[2], (domingo - self.hoje).days + 3)  # janela "antes": dom a ter

        dias = self.projetar(dias=7)

        no_domingo = next(d for d in dias if d.data == domingo)
        primeiro = next(d for d in dias if (parcela.pk, 'antes') in self.previstos(d))
        self.assertEqual(self.motivos(no_domingo)[parcela.pk], Motivo.DOMINGO_FERIADO)
        self.assertEqual(primeiro.data, next(d.data for d in dias if d.data > domingo and janela.dia_de_envio(d.data)))
        self.assertEqual(sum(1 for d in dias if (parcela.pk, 'antes') in self.previstos(d)), 1)

    def test_insistencias_seguem_o_intervalo_nos_proximos_dias(self):
        parcela = self.vencer_em(self.parcelas[2], -10)
        telefone = contatos.para_aviso(self.cliente)
        pedido = TentativaContato.objects.create(cliente=self.cliente, telefone=telefone, numero=telefone.telefone,
                                                 tipo=Tipo.AVISO_APOS, parcela=parcela)
        TentativaContato.objects.filter(pk=pedido.pk).update(criado_em=timezone.now() - timedelta(days=6))

        dias = self.projetar(dias=14)

        datas = [d.data for d in dias if (parcela.pk, 'insistencia') in self.previstos(d)]
        self.assertEqual(datas[0], self.hoje)
        self.assertGreaterEqual((datas[1] - datas[0]).days, 5)
        self.assertEqual(len(datas), 3)  # cobranca_max_insistencias
        self.assertEqual(agenda.dia_da_projecao(self.config(), saude(), datas[1], momento(self.hoje, 10)).data,
                         datas[1])


class HistoricoTests(CentralBase):
    def filtros(self, **extra) -> historico.Filtros:
        hoje = timezone.localdate()
        return historico.Filtros(desde=hoje - timedelta(days=1), ate=hoje + timedelta(days=1), **extra)

    def test_lista_status_da_mensagem_filtros_e_resumo(self):
        self.vencer_em(self.parcelas[2], 3)
        self.rodar()
        tentativa = TentativaContato.objects.get()

        self.assertEqual(historico.status_envio(historico.consultar(self.filtros()).get()), 'enviado')
        aplicar_status(tentativa.mensagem.wa_message_id, 'delivered')
        self.assertEqual(historico.consultar(self.filtros(status='entregue')).count(), 1)
        self.assertEqual(historico.consultar(self.filtros(etapa='dia')).count(), 0)
        resumo = historico.resumo(historico.consultar(self.filtros()))
        self.assertEqual((resumo['total'], resumo['por_etapa'], resumo['por_status']['entregue']),
                         (1, {'antes': 1}, 1))

        aplicar_status(tentativa.mensagem.wa_message_id, 'failed', [{'code': 131026, 'title': 'x'}])
        self.assertEqual(historico.consultar(self.filtros(status='falhou')).count(), 1)

    def test_escopo_de_lojas(self):
        self.vencer_em(self.parcelas[2], 3)
        self.rodar()

        self.assertEqual(historico.consultar(self.filtros(), self.atendente).count(), 0)  # sem vendas.view_cliente
        self.assertEqual(historico.consultar(self.filtros(), None).count(), 1)


class RotinaComAlertaTests(CentralBase):
    def test_teto_atingido_ainda_roda_os_alertas(self):
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=1)
        with mock.patch.object(teto, 'restante_no_dia', return_value=0), \
                mock.patch.object(cobranca._Rodada, 'alertas') as alertas:
            self.assertEqual(self.rodar(), {})
        alertas.assert_called_once()
