"""Régua ligada com data marcada: nada sai antes, e data de pagamento no futuro não vale como quitação."""
from datetime import timedelta

from crm.models import ConfiguracaoCRM, Mensagem, TentativaContato
from crm.tests.test_cobranca import ReguaBase, momento
from vendas.models import Parcela

Tipo = TentativaContato.Tipo


class InicioMarcadoTests(ReguaBase):
    def test_nada_sai_antes_da_data_marcada_nem_quitacao(self):
        Parcela.objects.filter(pagamento=self.pagamento).update(pago=True, data_pagamento=self.hoje)
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_ativada_em=momento(self.hoje + timedelta(days=3), 0))

        self.assertEqual(self.rodar(), {})
        self.assertFalse(Mensagem.objects.filter(origem=Mensagem.Origem.COBRANCA).exists())

    def test_comeca_no_dia_marcado(self):
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        self.vencer_em(self.parcelas[2], 0)
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_ativada_em=momento(self.hoje, 0))

        self.assertEqual(self.rodar(), {Tipo.AVISO_DIA: 1})

    def test_data_de_pagamento_no_futuro_nao_e_quitacao(self):
        Parcela.objects.filter(pagamento=self.pagamento).update(pago=True, data_pagamento=self.hoje)
        Parcela.objects.filter(pk=self.parcelas[2].pk).update(data_pagamento=self.hoje + timedelta(days=700))

        self.assertEqual(self.rodar(), {})
