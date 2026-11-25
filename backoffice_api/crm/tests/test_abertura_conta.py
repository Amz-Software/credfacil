"""Conversa no CRM a partir de contas a receber: conversa existente, aberturas com a parcela e envio."""
from datetime import timedelta

from django.utils import timezone

from backoffice_api.tests.fabricas import criar_loja
from crm.models import Conversa, Mensagem
from crm.tests.fabrica_cobranca import criar_cliente, criar_parcelas

from .base import CrmApiTestCase, url

CORPO_COBRANCA = 'Olá, {nome}! Sua parcela de {valor} vence em {vencimento}. Responda se precisar do PIX.'
CORPO_SIMPLES = 'Olá {nome}, temos uma novidade sobre o seu contrato.'
PODE_VER_TODAS = 'vendas.can_view_all_payments'


class AberturaDaContaTests(CrmApiTestCase):
    def setUp(self):
        super().setUp()
        self.loja = criar_loja()
        self.cliente = criar_cliente(self.loja, 'maria souza', '(91) 98888-1111', '12345678900')
        hoje = timezone.localdate()
        parcelas = criar_parcelas(self.cliente, self.gestor, [hoje - timedelta(days=5), hoje + timedelta(days=25)])
        self.vencida = parcelas[0]
        self.pagamento = self.vencida.pagamento
        self.cobranca = self.abertura_aprovada('Cobrança no dia', CORPO_COBRANCA)
        self.simples = self.abertura_aprovada('Novidade', CORPO_SIMPLES)
        self.atendente = self.dar_permissao(self.atendente, PODE_VER_TODAS)

    def contexto(self, usuario=None):
        return self.api(usuario).get(url(f'contas/{self.pagamento.pk}/abertura/'))

    def test_lista_aberturas_preenchidas_com_a_parcela_mais_antiga_em_aberto(self):
        resposta = self.contexto()

        self.assertEqual(resposta.status_code, 200, resposta.content)
        dados = resposta.json()
        self.assertEqual(dados['parcela']['numero'], self.vencida.numero_parcela)
        self.assertTrue(dados['parcela']['vencida'])
        cobranca = next(a for a in dados['aberturas'] if a['chave'] == self.cobranca.chave)
        self.assertTrue(cobranca['disponivel'])
        self.assertTrue(cobranca['cobranca'])
        vencimento = self.vencida.data_vencimento.strftime('%d/%m/%Y')
        self.assertEqual(cobranca['texto'],
                         f'Olá, Maria! Sua parcela de R$ 100,00 vence em {vencimento}. Responda se precisar do PIX.')
        simples = next(a for a in dados['aberturas'] if a['chave'] == self.simples.chave)
        self.assertEqual(simples['texto'], 'Olá Maria, temos uma novidade sobre o seu contrato.')

    def test_telefone_sem_conversa_e_com_conversa_existente(self):
        sem = self.contexto().json()['telefones'][0]
        self.assertEqual((sem['rotulo'], sem['conversa']), ('Principal', None))
        self.assertFalse(Conversa.objects.exists())  # consultar não cria conversa

        conversa = self.receber('oi', telefone='5591988881111', wamid='w1').conversa
        com = self.contexto().json()['telefones'][0]

        self.assertEqual(com['conversa']['id'], conversa.pk)
        self.assertTrue(com['conversa']['janela_aberta'])

    def test_iniciar_pela_conta_envia_cobranca_com_valor_e_vincula_o_cliente(self):
        resposta = self.api().post(url('conversas/iniciar/'), {
            'telefone': '91988881111', 'modelo': self.cobranca.chave, 'conta': self.pagamento.pk}, format='json')

        self.assertEqual(resposta.status_code, 201, resposta.content)
        conversa = Conversa.objects.get(pk=resposta.json()['id'])
        mensagem = Mensagem.objects.get(conversa=conversa)
        self.assertIn('R$ 100,00', mensagem.texto)
        self.assertIn('Maria', mensagem.texto)
        self.assertEqual(conversa.assumida_por, self.atendente)
        self.assertIn(self.cliente, conversa.clientes.all())

    def test_iniciar_pela_conta_so_aceita_telefone_do_cliente(self):
        resposta = self.api().post(url('conversas/iniciar/'), {
            'telefone': '91977776666', 'modelo': self.cobranca.chave, 'conta': self.pagamento.pk}, format='json')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('telefone', self.erro(resposta)['campos'])
        self.assertFalse(Conversa.objects.exists())

    def test_cobranca_sem_conta_continua_recusada(self):
        resposta = self.api().post(url('conversas/iniciar/'), {
            'telefone': '91988881111', 'modelo': self.cobranca.chave}, format='json')

        self.assertEqual(resposta.status_code, 409)

    def test_conta_de_outra_loja_sem_permissao_global_recebe_404(self):
        self.assertEqual(self.contexto(self.outro).status_code, 404)
        resposta = self.api(self.outro).post(url('conversas/iniciar/'), {
            'telefone': '91988881111', 'modelo': self.cobranca.chave, 'conta': self.pagamento.pk}, format='json')
        self.assertEqual(resposta.status_code, 404)
        self.assertFalse(Conversa.objects.exists())

    def test_sem_acesso_ao_crm_recebe_403(self):
        self.assertEqual(self.contexto(self.sem_acesso).status_code, 403)
