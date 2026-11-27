"""Disparo manual de cobrança: prévia, confirmação, envio pela rotina (ritmo, teto, 48 h, referência,
qualidade, recusas da Meta) e cancelamento."""
from datetime import date, timedelta
from unittest import mock

from django.utils import timezone

from crm.models import ConfiguracaoCRM, DisparoCobranca, ItemDisparo, Mensagem, TelefoneCliente, TentativaContato
from crm.services import cobranca, contatos
from crm.services.central_cobranca import disparos, envio_disparos, teto
from crm.services.central_cobranca.motivos import Motivo
from crm.services.conversas import ConflitoCRM
from crm.tests.test_central_cobranca import CentralBase, provider_com_numero, saude
from crm.tests.test_cobranca import momento
from crm.whatsapp import ErroWhatsApp
from vendas.models import ContatoAdicional, Parcela

Status = DisparoCobranca.Status
Situacao = ItemDisparo.Situacao
ATRASADOS = disparos.Publico(atraso_min=5, atraso_max=15)


class DisparoBase(CentralBase):
    def setUp(self):
        super().setUp()
        self.modelo = ConfiguracaoCRM.obter().modelo_aviso_apos
        self.atrasada = self.vencer_em(self.parcelas[2], -10)

    def previa(self, publico: disparos.Publico = ATRASADOS) -> DisparoCobranca:
        return disparos.montar_previa(self.modelo, publico, None)

    def agendado(self, publico: disparos.Publico = ATRASADOS) -> DisparoCobranca:
        return disparos.confirmar(self.previa(publico), self.gestor)

    def processar(self, hora: int = 10, dia: date | None = None) -> dict:
        with self.captureOnCommitCallbacks(execute=True):
            return envio_disparos.processar(momento(dia or self.hoje, hora), forcar=True)

    def situacoes(self, disparo: DisparoCobranca) -> dict[int, tuple[str, str]]:
        return {i.parcela_id: (i.situacao, i.motivo) for i in disparo.itens.all()}


class PreviaTests(DisparoBase):
    def test_publico_por_atraso_com_motivos_de_exclusao(self):
        _, ok = self.outro_cliente(1, -7)
        _, informada = self.outro_cliente(2, -8)
        Parcela.objects.filter(pk=informada.pk).update(pagamento_efetuado=True)
        recente, avisada = self.outro_cliente(3, -9)
        TentativaContato.objects.create(cliente=recente, numero='91988880003', tipo=TentativaContato.Tipo.AVISO_DIA)
        _, fora = self.outro_cliente(4, -30)
        segunda = criar_segunda_parcela(self.cliente, self.atendente, self.hoje - timedelta(days=6))

        disparo = self.previa()

        self.assertEqual((disparo.status, disparo.total, disparo.excluidos), (Status.PREVIA, 2, 3))
        self.assertEqual(self.situacoes(disparo), {
            self.atrasada.pk: (Situacao.PENDENTE, ''), ok.pk: (Situacao.PENDENTE, ''),
            informada.pk: (Situacao.EXCLUIDO, Motivo.PAGAMENTO_INFORMADO),
            avisada.pk: (Situacao.EXCLUIDO, Motivo.AVISO_RECENTE),
            segunda.pk: (Situacao.EXCLUIDO, Motivo.MESMO_CLIENTE),
        })
        self.assertNotIn(fora.pk, self.situacoes(disparo))
        self.assertFalse(Mensagem.objects.exists())  # prévia não envia nada

    def test_outros_criterios_e_parcelas_nao_encontradas(self):
        _, dia10 = self.outro_cliente(1, (disparos.proxima_ocorrencia(10, self.hoje) - self.hoje).days)
        _, data = self.outro_cliente(2, 4)

        por_dia = self.previa(disparos.Publico(vencimento_dia=10))
        por_data = self.previa(disparos.Publico(vencimento_data=self.hoje + timedelta(days=4)))
        por_lista = self.previa(disparos.Publico(parcelas=(data.pk, 999999)))

        self.assertIn(dia10.pk, self.situacoes(por_dia))
        self.assertEqual(set(self.situacoes(por_data)), {data.pk})
        self.assertEqual(por_lista.filtros['nao_encontradas'], [999999])
        self.assertEqual(disparos.proxima_ocorrencia(1, date(2026, 12, 15)), date(2027, 1, 1))

    def test_referencia_nunca_recebe(self):
        self.cliente.contato_adicional = ContatoAdicional.objects.create(nome_adicional='João', contato='91977770000')
        self.cliente.save()
        contatos.mudar_situacao(contatos.para_aviso(self.cliente), TelefoneCliente.Situacao.SEM_WHATSAPP)

        disparo = self.previa()

        self.assertEqual(self.situacoes(disparo)[self.atrasada.pk], (Situacao.EXCLUIDO, Motivo.SO_REFERENCIA))

    def test_modelo_nao_aprovado_e_publico_grande_demais(self):
        self.modelo.versoes.update(vigente=False)
        with self.assertRaises(ConflitoCRM):
            self.previa()
        self.modelo.versoes.update(vigente=True)
        with mock.patch.object(disparos, 'MAX_DESTINATARIOS', 0), self.assertRaises(ConflitoCRM):
            self.previa()

    def test_confirmar_so_previa_valida(self):
        vazia = self.previa(disparos.Publico(atraso_min=100, atraso_max=200))
        with self.assertRaises(ConflitoCRM):
            disparos.confirmar(vazia, self.gestor)
        antiga = self.previa()
        DisparoCobranca.objects.filter(pk=antiga.pk).update(criado_em=timezone.now() - timedelta(days=2))
        with self.assertRaises(ConflitoCRM):
            disparos.confirmar(antiga, self.gestor)

        confirmado = self.agendado()
        self.assertEqual((confirmado.status, confirmado.confirmado_por), (Status.AGENDADO, self.gestor))
        with self.assertRaises(ConflitoCRM):
            disparos.confirmar(confirmado, self.gestor)

    def test_distribuicao_pelo_teto_e_pelo_ritmo(self):
        config = ConfiguracaoCRM.obter()
        dias, sobra = disparos.distribuicao(30, config, saude(teto_configurado=10), momento(self.hoje, 19))

        self.assertEqual(dias[0], (self.hoje, 10))
        self.assertEqual(sum(qtd for _, qtd in dias) + sobra, 30)
        self.assertEqual(disparos.distribuicao(5, config, saude('RED')), ([], 5))


class EnvioTests(DisparoBase):
    def test_previa_igual_ao_envio_e_conclui(self):
        _, outra = self.outro_cliente(1, -7)
        disparo = self.agendado()
        pendentes = {i.parcela_id for i in disparo.itens.filter(situacao=Situacao.PENDENTE)}

        self.assertEqual(self.processar(), {disparo.pk: 2})

        disparo.refresh_from_db()
        enviados = set(TentativaContato.objects.filter(tipo=TentativaContato.Tipo.DISPARO, sequencia=disparo.pk)
                       .values_list('parcela_id', flat=True))
        self.assertEqual(enviados, pendentes)
        self.assertEqual((disparo.status, disparo.enviados, disparo.falhas), (Status.CONCLUIDO, 2, 0))
        self.assertTrue(all(i.tentativa_id for i in disparo.itens.filter(situacao=Situacao.ENVIADO)))
        self.assertIn('R$ 100,00', Mensagem.objects.filter(origem=Mensagem.Origem.COBRANCA).first().texto)

    def test_ritmo_por_minuto(self):
        for numero in range(1, 25):
            self.outro_cliente(numero, -7)
        disparo = self.agendado()

        primeiro = self.processar()
        segundo = self.processar()

        self.assertEqual(primeiro, {disparo.pk: disparos.ENVIOS_POR_MINUTO})
        self.assertEqual(segundo, {disparo.pk: 25 - disparos.ENVIOS_POR_MINUTO})

    def test_teto_do_dia_deixa_o_resto_para_depois(self):
        for numero in range(1, 5):
            self.outro_cliente(numero, -7)
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_teto_diario=3)
        disparo = self.agendado()

        self.assertEqual(self.processar(), {disparo.pk: 3})
        self.assertEqual(self.processar(), {})  # teto do dia esgotado: nada é examinado
        disparo.refresh_from_db()
        self.assertEqual((disparo.status, disparo.itens.filter(situacao=Situacao.PENDENTE).count()),
                         (Status.ENVIANDO, 2))

    def test_fora_da_janela_domingo_e_qualidade_nao_envia(self):
        disparo = self.agendado()
        domingo = self.hoje + timedelta(days=(6 - self.hoje.weekday()) % 7 or 7)

        self.assertEqual(self.processar(hora=7), {})
        self.assertEqual(self.processar(hora=21), {})
        self.assertEqual(self.processar(dia=domingo), {})
        with mock.patch.object(teto, 'obter_provider', return_value=provider_com_numero('TIER_2K', 'RED')):
            teto.limpar_cache()
            self.assertEqual(self.processar(), {})
        self.assertEqual(DisparoCobranca.objects.get(pk=disparo.pk).enviados, 0)

    def test_regra_das_48_horas_e_referencia_no_envio(self):
        recente, parcela_recente = self.outro_cliente(1, -7)
        sem_numero, parcela_ref = self.outro_cliente(2, -8)
        disparo = self.agendado()
        TentativaContato.objects.create(cliente=recente, numero='91988880001', tipo=TentativaContato.Tipo.AVISO_DIA)
        sem_numero.contato_adicional = ContatoAdicional.objects.create(nome_adicional='Ref', contato='91966660000')
        sem_numero.save()
        contatos.mudar_situacao(contatos.para_aviso(sem_numero), TelefoneCliente.Situacao.INVALIDO)

        self.processar()

        situacoes = self.situacoes(disparo)
        self.assertEqual(situacoes[parcela_recente.pk], (Situacao.IGNORADO, Motivo.AVISO_RECENTE))
        self.assertEqual(situacoes[parcela_ref.pk], (Situacao.IGNORADO, Motivo.SO_REFERENCIA))
        self.assertFalse(Mensagem.objects.filter(conversa__telefone__endswith='66660000').exists())
        self.assertEqual(DisparoCobranca.objects.get(pk=disparo.pk).ignorados, 2)

    def test_parcela_paga_depois_da_previa_e_ignorada(self):
        disparo = self.agendado()
        Parcela.objects.filter(pk=self.atrasada.pk).update(pago=True)

        self.processar()

        self.assertEqual(self.situacoes(disparo)[self.atrasada.pk], (Situacao.IGNORADO, Motivo.PARCELA_PAGA))

    def test_cancelado_nao_sai(self):
        disparo = disparos.cancelar(self.agendado(), self.gestor)

        self.assertEqual(self.processar(), {})
        self.assertEqual((disparo.status, disparo.cancelado_por), (Status.CANCELADO, self.gestor))
        with self.assertRaises(ConflitoCRM):
            disparos.cancelar(disparo, self.gestor)

    def test_recusas_seguidas_da_meta_pausam_e_retomar_volta_a_fila(self):
        for numero in range(1, 6):
            self.outro_cliente(numero, -7)
        disparo = self.agendado()
        provider = mock.Mock(enviar_template=mock.Mock(side_effect=ErroWhatsApp('token vencido', 190)))

        with mock.patch.object(cobranca, 'obter_provider', return_value=provider):
            self.processar()

        disparo.refresh_from_db()
        self.assertEqual((disparo.status, disparo.falhas), (Status.PAUSADO, cobranca.MAX_FALHAS_SEGUIDAS))
        self.assertIn('token vencido', disparo.motivo_pausa)
        self.assertEqual(disparos.retomar(disparo).status, Status.AGENDADO)
        self.assertEqual(self.processar(), {disparo.pk: 1})

    def test_template_que_deixou_de_valer_pausa(self):
        disparo = self.agendado()
        self.modelo.versoes.update(vigente=False)

        self.processar()

        self.assertEqual(DisparoCobranca.objects.get(pk=disparo.pk).status, Status.PAUSADO)

    def test_disparo_conta_como_aviso_do_dia_para_a_regua(self):
        disparo = self.agendado()
        self.processar()
        Parcela.objects.filter(pk=self.parcelas[0].pk).update(pago=False, data_vencimento=self.hoje)

        self.assertEqual(self.rodar(), {})
        self.assertEqual(TentativaContato.objects.get().sequencia, disparo.pk)

    def test_situacao_de_envio(self):
        config = ConfiguracaoCRM.obter()
        self.assertEqual(disparos.situacao_envio(config, saude(), momento(self.hoje, 7)), Motivo.FORA_DO_HORARIO)
        self.assertEqual(disparos.situacao_envio(config, saude('YELLOW'), momento(self.hoje, 10)),
                         Motivo.PAUSADA_POR_QUALIDADE)
        self.assertEqual(disparos.situacao_envio(config, saude(), momento(self.hoje, 10)), '')


def criar_segunda_parcela(cliente, vendedor, vencimento: date):
    from crm.tests.fabrica_cobranca import criar_parcelas

    return criar_parcelas(cliente, vendedor, [vencimento])[0]
