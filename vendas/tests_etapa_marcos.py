"""De quem é a vez (filtro da SPA) e marcos da linha do tempo do vendedor."""
from django.test import TestCase

from vendas.models import AnaliseCreditoCliente, Venda
from vendas.services import analise as servico_analise
from vendas.services.etapa_vendedor import AGUARDANDO_ANALISTA, MINHA_ACAO, contar_por_etapa, filtro_etapa
from vendas.services.marcos_solicitacao import marcos_da_solicitacao
from vendas.tests_services import CenarioMixin


def etapa_de(analise) -> str | None:
    qs = AnaliseCreditoCliente.objects.filter(pk=analise.pk)
    for etapa in (MINHA_ACAO, AGUARDANDO_ANALISTA):
        if qs.filter(filtro_etapa(etapa)).exists():
            return etapa
    return None


class EtapaVendedorTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def _mudar(self, **campos):
        for campo, valor in campos.items():
            setattr(self.analise, campo, valor)
        self.analise.save()

    def test_android_passo_a_passo(self):
        self._mudar(status='EA', status_aplicativo='P', imei=None)
        self.assertEqual(etapa_de(self.analise), AGUARDANDO_ANALISTA)
        self._mudar(status='A')
        self.assertEqual(etapa_de(self.analise), MINHA_ACAO)  # instalar o app
        self._mudar(status_aplicativo='C')
        self.assertEqual(etapa_de(self.analise), AGUARDANDO_ANALISTA)
        self._mudar(status_aplicativo='I', imei=self.imei)
        self.assertEqual(etapa_de(self.analise), MINHA_ACAO)  # gerar a venda
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=self.loja, repasse_logista=0)
        self._mudar(venda=venda)
        self.assertIsNone(etapa_de(self.analise))

    def test_iphone_passo_a_passo(self):
        self.produto.is_iphone = True
        self.produto.save()
        self._mudar(status='A', imei=None, status_aplicativo='P')
        self.assertEqual(etapa_de(self.analise), MINHA_ACAO)  # configuração inicial
        self._mudar(icloud_configurado_vendedor=True)
        self.assertEqual(etapa_de(self.analise), AGUARDANDO_ANALISTA)
        self._mudar(imei_informado='350000000000001')
        self.assertEqual(etapa_de(self.analise), MINHA_ACAO)

    def test_encerradas_nao_entram(self):
        for status in ('R', 'C'):
            self._mudar(status=status)
            self.assertIsNone(etapa_de(self.analise))

    def test_contagem_e_etapa_desconhecida(self):
        self._mudar(status='EA')
        self.assertEqual(contar_por_etapa(AnaliseCreditoCliente.objects.all()), {MINHA_ACAO: 0, AGUARDANDO_ANALISTA: 1})
        self.assertIsNone(filtro_etapa('qualquer'))


class MarcosSolicitacaoTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.analise.status, self.analise.status_aplicativo, self.analise.imei = 'EA', 'P', None
        self.analise.save()
        # O cenário nasce aprovado: recomeça o histórico como uma solicitação recém-enviada.
        self.analise.history.all().delete()
        self.analise.save()

    def test_fluxo_android_vira_marcos_na_ordem(self):
        servico_analise.aprovar_analise(self.analise, self.analista)
        servico_analise.confirmar_instalacao_vendedor(self.analise, self.vendedor, digitos='0001')
        servico_analise.informar_imei(self.analise, self.analista, self.imei.imei, self.loja)

        tipos = [m['tipo'] for m in marcos_da_solicitacao(self.analise, self.vendedor)]

        self.assertEqual(tipos, ['enviada', 'status_A', 'instalacao_confirmada', 'aparelho_validado'])

    def test_nao_expoe_campos_internos_e_marca_por_voce(self):
        self.analise.observacao = 'interna'
        self.analise.save()

        marcos = marcos_da_solicitacao(self.analise, self.vendedor)

        self.assertEqual([m['tipo'] for m in marcos], ['enviada'])
        self.assertFalse(marcos[0]['por_voce'])
        self.assertIn('T', marcos[0]['data'])


class ResumoVendaTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def test_previa_usa_o_mesmo_calculo_da_venda(self):
        from vendas.services.venda import resumo_da_venda

        resumo = resumo_da_venda(self.analise)

        # (1200 - 200) * 1,20 = 1200 em 10x
        self.assertEqual(
            (resumo['entrada'], resumo['parcelas'], resumo['valor_parcela'], resumo['total_financiado']),
            ('200.00', 10, '120.00', '1200.00'),
        )
        self.assertIsNotNone(resumo['primeiro_vencimento'])

    def test_sem_parcelamento_nao_tem_previa(self):
        from vendas.services.venda import resumo_da_venda

        self.analise.numero_parcelas = '7'
        self.assertIsNone(resumo_da_venda(self.analise))


class VendaLiberadaIphoneTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario(is_iphone=True)
        self.analise.imei, self.analise.criado_por = None, self.vendedor
        self.analise.icloud_configurado_vendedor = True
        self.analise.save()

    def test_imei_informado_avisa_o_vendedor(self):
        from notifications.models import Notification

        servico_analise.informar_imei(self.analise, self.analista, self.imei.imei, self.loja)

        avisos = Notification.objects.filter(recipient=self.vendedor, verb__contains='Venda liberada')
        self.assertEqual(avisos.count(), 1)

        self.analise.save()  # gravar de novo não repete o aviso
        self.assertEqual(avisos.count(), 1)
