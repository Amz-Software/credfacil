from crm.models import VersaoAbertura
from crm.services import aberturas
from crm.services.conversas import ConflitoCRM
from crm.tests.base import CrmTestCase


class AberturasTests(CrmTestCase):
    def test_validacao_do_corpo(self):
        self.assertEqual(aberturas.validar_corpo('Olá {nome}, tudo bem com você?'), [])
        self.assertTrue(aberturas.validar_corpo('{nome} oi'))
        self.assertTrue(aberturas.validar_corpo('Olá {cliente}, tudo bem?'))
        self.assertTrue(aberturas.validar_corpo('Olá {nome} {nome} tudo bem por aí?'))

    def test_versoes_em_analise_aprovacao_e_promocao(self):
        modelo = aberturas.criar_modelo('Retomar', 'Olá {nome}, podemos continuar o atendimento?', self.gestor)
        primeira = modelo.versoes.get()

        with self.assertRaises(ConflitoCRM):
            aberturas.editar_modelo(modelo, {'corpo': 'Outro texto para o cliente agora'}, self.gestor)
        aberturas.simular_decisao(modelo, 'APROVADO')
        aberturas.editar_modelo(modelo, {'corpo': 'Olá {nome}, vamos retomar seu atendimento?'}, self.gestor)

        primeira.refresh_from_db()
        segunda = modelo.versoes.get(versao=2)
        self.assertTrue(primeira.vigente)
        self.assertEqual(segunda.status, VersaoAbertura.Status.EM_ANALISE)
        self.assertEqual(segunda.nome_meta, 'abertura_retomar_v2')
        self.assertEqual(segunda.corpo_meta, 'Olá {{1}}, vamos retomar seu atendimento?')
        disponivel = [a for a in aberturas.disponiveis() if a['chave'] == modelo.chave][0]
        self.assertTrue(disponivel['disponivel'])
        self.assertEqual(disponivel['texto'], primeira.corpo)

    def test_decidida_nao_volta_para_analise(self):
        modelo = aberturas.criar_modelo('Status', 'Olá {nome}, sua proposta foi analisada.', self.gestor)
        versao = modelo.versoes.get()
        aberturas.aplicar_status_meta(versao, 'APPROVED', 'UTILITY')

        aberturas.aplicar_status_meta(versao, 'PENDING')

        versao.refresh_from_db()
        self.assertEqual(versao.status, VersaoAbertura.Status.APROVADO)
