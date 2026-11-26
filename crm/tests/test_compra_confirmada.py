"""Mensagem de compra confirmada ao cliente quando o vendedor gera a venda."""
from datetime import date, timedelta
from unittest import mock

from crm.models import ConfiguracaoCRM, Mensagem
from crm.services import compra_confirmada
from crm.tests.base import CrmTestCase
from crm.tests.fabrica_cobranca import criar_cliente, criar_parcelas
from crm.whatsapp import ErroWhatsApp
from vendas.models import Loja

CORPO = 'Olá, {nome}! Sua compra foi confirmada. A primeira parcela de {valor} vence em {vencimento}. Responda aqui.'


class CompraConfirmadaTests(CrmTestCase):
    def setUp(self):
        super().setUp()
        loja = Loja.objects.create(nome='Centro')
        self.cliente = criar_cliente(loja, 'maria souza', '91988887777', '12345678900')
        vencimento = date.today() + timedelta(days=20)
        self.venda = criar_parcelas(self.cliente, self.atendente, [vencimento, vencimento + timedelta(days=30)])[0].pagamento.venda
        self.vencimento = vencimento

    def _ligar(self):
        modelo = self.abertura_aprovada('Compra confirmada', CORPO)
        ConfiguracaoCRM.objects.filter(pk=1).update(modelo_compra_confirmada=modelo)

    def test_sem_template_nao_agenda_nada(self):
        self.assertFalse(compra_confirmada.agendar(self.venda))
        self.assertIsNone(compra_confirmada.enviar(self.venda.pk))

    def test_envia_uma_vez_com_primeira_parcela(self):
        self._ligar()

        with self.em_commit():
            self.assertTrue(compra_confirmada.agendar(self.venda))
        compra_confirmada.enviar(self.venda.pk)  # repetir não manda de novo

        mensagens = Mensagem.objects.filter(origem=Mensagem.Origem.COMPRA)
        self.assertEqual(mensagens.count(), 1)
        mensagem = mensagens.get()
        self.assertEqual(mensagem.status, Mensagem.Status.ENVIADO)
        self.assertIn('Olá, Maria!', mensagem.texto)
        self.assertIn('R$ 100,00', mensagem.texto)
        self.assertIn(self.vencimento.strftime('%d/%m/%Y'), mensagem.texto)
        self.assertIn(self.cliente, mensagem.conversa.clientes.all())

    def test_falha_da_meta_marca_erro_sem_levantar(self):
        self._ligar()

        with mock.patch('crm.whatsapp.ProviderSimulado.enviar_template', side_effect=ErroWhatsApp('fora do ar', 1)):
            self.assertIsNone(compra_confirmada.enviar(self.venda.pk))

        self.assertEqual(Mensagem.objects.get(origem=Mensagem.Origem.COMPRA).status, Mensagem.Status.ERRO)
