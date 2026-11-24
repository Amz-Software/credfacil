"""Assistente com o PagBank: Pix direto (copia e cola enviado pelo sistema) e link do app do cliente."""
import json
from unittest import mock

from django.test import override_settings

from crm.models import Mensagem
from crm.tests.test_assistente import IDENTIDADE_CERTA, AssistenteBase, ferramenta, texto
from pagamentos_online.models import Cobranca, ConfiguracaoPagamentoOnline
from pagamentos_online.tests.base import RespostaFalsa, resposta_pix

COPIA_COLA = '00020101021226850014br.gov.bcb.pix2563qr.pagseguro.com.br/pix/v2/cobv/abc'


def _pix(metodo, url, **kwargs):
    corpo = resposta_pix(kwargs['json']['reference_id'])
    corpo['charges'][0]['qr_code']['text'] = COPIA_COLA
    return RespostaFalsa(201, corpo)


@override_settings(PAGBANK_TOKEN='token-de-teste')
class AssistentePagBankTests(AssistenteBase):
    def setUp(self):
        super().setUp()
        configuracao = ConfiguracaoPagamentoOnline.obter()
        configuracao.ativo = True
        configuracao.email_padrao = 'cobranca@exemplo.com'
        configuracao.url_app_cliente = 'https://vendas.exemplo.com'
        configuracao.save()

    def saidas(self) -> list[str]:
        return list(Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('id').values_list('texto', flat=True))

    def test_pix_direto_manda_o_copia_e_cola_numa_mensagem_separada(self):
        parcela = self.parcela_aberta()
        roteiro = self.com_roteiro(
            ferramenta('identificar_cliente', IDENTIDADE_CERTA),
            ferramenta('gerar_link_pagamento', {'parcela_id': parcela.pk, 'forma': 'pix'}, 'tu_2'),
            texto('Prontinho, Maria! O Pix de R$ 100,00 vai logo abaixo.'),
        )
        with mock.patch('pagamentos_online.pagbank.cliente.requests.request', side_effect=_pix):
            self.receber('cpf 529.982.247-25, nasci 17/05/1990, me manda o pix', wamid='w1')
        resultado = json.loads(roteiro.resultado(2)['content'])
        self.assertEqual(resultado['forma'], 'pix')
        self.assertNotIn('copia_cola', resultado)
        self.assertEqual(self.saidas()[-2:], ['Prontinho, Maria! O Pix de R$ 100,00 vai logo abaixo.', COPIA_COLA])
        self.assertEqual(Cobranca.objects.get().origem, Cobranca.Origem.BOT)

    def test_link_do_app_do_cliente_e_permitido_na_resposta(self):
        parcela = self.parcela_aberta()
        roteiro = self.com_roteiro(
            ferramenta('identificar_cliente', IDENTIDADE_CERTA),
            ferramenta('gerar_link_pagamento', {'parcela_id': parcela.pk}, 'tu_2'),
            lambda _: texto(f'Aqui está: {json.loads(roteiro.resultado(2)["content"])["url"]}'),
        )
        self.receber('cpf 529.982.247-25, nasci 17/05/1990, quero pagar', wamid='w1')
        resultado = json.loads(roteiro.resultado(2)['content'])
        self.assertEqual(resultado['forma'], 'pagina_do_cliente')
        self.assertTrue(resultado['url'].startswith('https://vendas.exemplo.com/pagamento/'))
        self.assertIn('vendas.exemplo.com', self.saidas()[-1])

    def test_pix_indisponivel_cai_no_link_da_pagina(self):
        ConfiguracaoPagamentoOnline.objects.filter(pk=1).update(ativo=False)
        parcela = self.parcela_aberta()
        roteiro = self.com_roteiro(
            ferramenta('identificar_cliente', IDENTIDADE_CERTA),
            ferramenta('gerar_link_pagamento', {'parcela_id': parcela.pk, 'forma': 'pix'}, 'tu_2'),
            texto('Segue o link.'),
        )
        self.receber('cpf 529.982.247-25, nasci 17/05/1990, pix', wamid='w1')
        resultado = json.loads(roteiro.resultado(2)['content'])
        self.assertIn('url', resultado)
        self.assertIn('observacao', resultado)
        self.assertFalse(Cobranca.objects.exists())
