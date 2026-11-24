"""Tamanho de papel dos PDFs com listas (`papel` + `orientacao`)."""
from django.test import SimpleTestCase

from backoffice_api.nucleo.erros import ErroBackoffice
from backoffice_api.nucleo.papel import tamanho_pagina


class TamanhoPaginaTests(SimpleTestCase):
    def test_sem_parametros_mantem_a4_paisagem(self):
        self.assertEqual(tamanho_pagina({}), 'A4 landscape')

    def test_traduz_papel_e_orientacao_para_css(self):
        self.assertEqual(tamanho_pagina({'papel': 'A2'}), 'A2 landscape')
        self.assertEqual(tamanho_pagina({'papel': 'oficio', 'orientacao': 'retrato'}), 'legal portrait')

    def test_valor_fora_da_lista_e_recusado_com_campo(self):
        for parametros, campo in (({'papel': 'A2; color: red'}, 'papel'), ({'orientacao': 'deitado'}, 'orientacao')):
            with self.subTest(campo=campo), self.assertRaises(ErroBackoffice) as erro:
                tamanho_pagina(parametros)
            self.assertIn(campo, erro.exception.campos)
