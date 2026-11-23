"""Parcelamentos: permissões, escopo pela marca, unicidade, auditoria e exclusão."""
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from produtos.models import Parcelamento

from .base import URL, CatalogoTestCase, criar_marca, criar_parcelamento, ids

URL_PARC = f'{URL}/parcelamentos/'
TODAS = ('produtos.view_parcelamento', 'produtos.add_parcelamento', 'produtos.change_parcelamento')


def url_parc(parcelamento) -> str:
    return f'{URL_PARC}{parcelamento.pk}/'


class ParcelamentosTests(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.livre = criar_marca('Livre')
        cls.marca_b = criar_marca('Marca B', lojas=(cls.loja_b,))
        cls.p4 = criar_parcelamento(cls.livre, 4, '20')
        cls.p10 = criar_parcelamento(cls.livre, 10, '50')
        cls.pb = criar_parcelamento(cls.marca_b, 6, '30')

    def _cliente(self, permissoes=TODAS):
        self.user = criar_usuario('gestor', permissoes=permissoes, lojas=(self.loja_a,))
        return cliente_logado(self.user)

    def test_sem_permissao_recebe_403(self):
        self.assertErro(self._cliente(()).get(URL_PARC), 403, 'proibido')

    def test_lista_so_marcas_visiveis_com_busca(self):
        cliente = self._cliente()
        self.assertEqual(ids(cliente.get(URL_PARC)), {self.p4.pk, self.p10.pk})
        self.assertEqual(ids(cliente.get(URL_PARC, {'busca': '10'})), {self.p10.pk})
        self.assertEqual(ids(cliente.get(URL_PARC, {'busca': 'livr'})), {self.p4.pk, self.p10.pk})
        self.assertErro(cliente.get(url_parc(self.pb)), 404, 'nao_encontrado')
        primeiro = cliente.get(URL_PARC, {'ordenar': '-qtd_vezes'}).json()['results'][0]
        self.assertEqual(primeiro['marca']['nome'], 'Livre')
        self.assertEqual(primeiro['qtd_vezes'], 10)

    def test_criar_auditado(self):
        cliente = self._cliente()
        corpo = {'marca': self.livre.pk, 'qtd_vezes': 12, 'porcentagem_juros': '60.00', 'porcentagem_desconto': '5'}
        resposta = cliente.post(URL_PARC, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        parcelamento = Parcelamento.objects.get(pk=resposta.json()['id'])
        self.assertEqual(self.assertAuditado('parcelamento_criado', parcelamento).dados['depois']['qtd_vezes'], 12)

    def test_duplicado_tem_mensagem_clara(self):
        corpo = {'marca': self.livre.pk, 'qtd_vezes': 4, 'porcentagem_juros': '10'}
        erro = self.assertErro(self._cliente().post(URL_PARC, corpo, format='json'), 400, 'validacao', 'qtd_vezes')
        self.assertEqual(erro['mensagem'], 'Já existe um parcelamento de 4x cadastrado para a marca Livre.')

    def test_editar_para_duplicado_e_editar_valido(self):
        cliente = self._cliente()
        self.assertErro(cliente.patch(url_parc(self.p10), {'qtd_vezes': 4}, format='json'), 400, 'validacao',
                        'qtd_vezes')
        resposta = cliente.patch(url_parc(self.p10), {'porcentagem_juros': '45.50'}, format='json')
        self.assertEqual(resposta.json()['porcentagem_juros'], '45.50')
        registro = self.assertAuditado('parcelamento_alterado', self.p10)
        self.assertEqual((registro.dados['antes']['porcentagem_juros'], registro.dados['depois']['porcentagem_juros']),
                         ('50.00', '45.50'))

    def test_validacoes_de_faixa_e_marca(self):
        cliente = self._cliente()
        zero = {'marca': self.livre.pk, 'qtd_vezes': 0, 'porcentagem_juros': '10'}
        self.assertErro(cliente.post(URL_PARC, zero, format='json'), 400, 'validacao', 'qtd_vezes')
        negativo = {'marca': self.livre.pk, 'qtd_vezes': 3, 'porcentagem_juros': '-1'}
        self.assertErro(cliente.post(URL_PARC, negativo, format='json'), 400, 'validacao', 'porcentagem_juros')
        outra_loja = {'marca': self.marca_b.pk, 'qtd_vezes': 3, 'porcentagem_juros': '10'}
        self.assertErro(cliente.post(URL_PARC, outra_loja, format='json'), 400, 'validacao', 'marca')

    def test_excluir_definitivo_e_auditado(self):
        cliente = self._cliente(TODAS + ('produtos.delete_parcelamento',))
        self.assertEqual(cliente.delete(url_parc(self.p4)).status_code, 204)
        self.assertFalse(Parcelamento.objects.filter(pk=self.p4.pk).exists())
        self.assertAuditado('parcelamento_excluido', self.p4)

    def test_excluir_exige_delete_e_put_nao_existe(self):
        cliente = self._cliente()
        self.assertErro(cliente.delete(url_parc(self.p4)), 403, 'proibido')
        self.assertErro(cliente.put(url_parc(self.p4), {}, format='json'), 405, 'metodo_nao_permitido')
        self.assertTrue(Parcelamento.objects.filter(pk=self.p4.pk).exists())
