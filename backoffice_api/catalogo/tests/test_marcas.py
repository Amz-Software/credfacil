"""Marcas: escopo de lojas permitidas, filtro de situação, escrita e ativar/desativar."""
from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from produtos.models import Marca

from .base import URL, CatalogoTestCase, criar_marca, criar_parcelamento, criar_produto, ids

URL_MARCAS = f'{URL}/marcas/'
VER = ('produtos.view_marca',)
ESCRITA = ('produtos.view_marca', 'produtos.add_marca', 'produtos.change_marca')


def url_marca(marca, acao: str = '') -> str:
    return f'{URL_MARCAS}{marca.pk}/' + (f'{acao}/' if acao else '')


class MarcasBase(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.loja_a = criar_loja('Loja A')
        cls.loja_b = criar_loja('Loja B')
        cls.livre = criar_marca('Livre')
        cls.da_a = criar_marca('Da A', lojas=(cls.loja_a,))
        cls.da_b = criar_marca('Da B', lojas=(cls.loja_b,))
        cls.inativa = criar_marca('Inativa', ativo=False)
        criar_produto('P1', cls.livre)
        criar_parcelamento(cls.livre, 4, '10')
        criar_parcelamento(cls.livre, 6, '15')


class ListaDeMarcasTests(MarcasBase):
    def test_sem_permissao_recebe_403(self):
        self.assertErro(cliente_logado(criar_usuario('semperm', lojas=(self.loja_a,))).get(URL_MARCAS), 403,
                        'proibido')

    def test_padrao_so_ativas_visiveis_para_a_loja(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=VER, lojas=(self.loja_a,)))
        resposta = cliente.get(URL_MARCAS)
        self.assertEqual(ids(resposta), {self.livre.pk, self.da_a.pk})
        por_id = {m['id']: m for m in resposta.json()['results']}
        self.assertEqual(por_id[self.da_a.pk]['lojas_permitidas'], [{'id': self.loja_a.pk, 'nome': 'Loja A'}])
        self.assertEqual((por_id[self.livre.pk]['total_produtos'], por_id[self.livre.pk]['total_parcelamentos']),
                         (1, 2))

    def test_filtro_de_situacao(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(ids(cliente.get(URL_MARCAS, {'ativo': 'nao'})), {self.inativa.pk})
        self.assertEqual(ids(cliente.get(URL_MARCAS, {'ativo': 'todos'})),
                         {self.livre.pk, self.da_a.pk, self.inativa.pk})
        self.assertErro(cliente.get(URL_MARCAS, {'ativo': 'x'}), 400, 'validacao', 'ativo')

    def test_administrador_global_ve_todas_ou_filtra_pela_loja(self):
        cliente = cliente_logado(criar_usuario('adm', permissoes=VER + ('vendas.can_view_all_stores',)))
        self.assertEqual(ids(cliente.get(URL_MARCAS, HTTP_X_LOJA='todas')), {self.livre.pk, self.da_a.pk, self.da_b.pk})
        self.assertEqual(ids(cliente.get(URL_MARCAS, HTTP_X_LOJA=str(self.loja_b.pk))), {self.livre.pk, self.da_b.pk})

    def test_marca_de_outra_loja_responde_404(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.get(url_marca(self.da_b)), 404, 'nao_encontrado')
        self.assertEqual(cliente.get(url_marca(self.da_a)).status_code, 200)

    def test_icones(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=VER))
        resposta = cliente.get(f'{URL_MARCAS}icones/')
        self.assertEqual(len(resposta.json()), len(Marca.ICONE_CHOICES))
        self.assertEqual(resposta.json()[0], {'valor': 'bi bi-apple', 'rotulo': 'Apple'})


class EscritaDeMarcasTests(MarcasBase):
    def test_criar_com_lojas_do_escopo(self):
        user = criar_usuario('cad', permissoes=ESCRITA, lojas=(self.loja_a,))
        corpo = {'nome': 'Nova', 'cor': '#ff0000', 'icone': 'bi bi-apple', 'lojas_permitidas': [self.loja_a.pk]}
        resposta = cliente_logado(user).post(URL_MARCAS, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        marca = Marca.objects.get(pk=resposta.json()['id'])
        self.assertEqual((marca.criado_por, list(marca.lojas_permitidas.all())), (user, [self.loja_a]))
        self.assertTrue(resposta.json()['ativo'])

    def test_criar_valida_lojas_cor_e_icone(self):
        cliente = cliente_logado(criar_usuario('cad', permissoes=ESCRITA, lojas=(self.loja_a,)))
        fora = {'nome': 'X', 'lojas_permitidas': [self.loja_b.pk]}
        self.assertErro(cliente.post(URL_MARCAS, fora, format='json'), 400, 'validacao', 'lojas_permitidas')
        cor = {'nome': 'X', 'cor': 'red;background:url(x)'}
        self.assertErro(cliente.post(URL_MARCAS, cor, format='json'), 400, 'validacao', 'cor')
        icone = {'nome': 'X', 'icone': 'fa fa-skull'}
        self.assertErro(cliente.post(URL_MARCAS, icone, format='json'), 400, 'validacao', 'icone')

    def test_criar_exige_permissao(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(cliente.post(URL_MARCAS, {'nome': 'X'}, format='json'), 403, 'proibido')

    def test_editar_preserva_lojas_fora_do_escopo(self):
        marca = criar_marca('Das duas', lojas=(self.loja_a, self.loja_b))
        cliente = cliente_logado(criar_usuario('ed', permissoes=ESCRITA, lojas=(self.loja_a,)))
        resposta = cliente.patch(url_marca(marca), {'nome': 'Renomeada', 'lojas_permitidas': []}, format='json')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.json()['lojas_permitidas'], [])
        self.assertEqual(set(marca.lojas_permitidas.values_list('pk', flat=True)), {self.loja_b.pk})
        self.assertEqual(Marca.objects.get(pk=marca.pk).nome, 'Renomeada')

    def test_administrador_global_substitui_as_lojas(self):
        marca = criar_marca('Das duas', lojas=(self.loja_a, self.loja_b))
        cliente = cliente_logado(criar_usuario('adm', permissoes=ESCRITA + ('vendas.can_view_all_stores',)))
        cliente.patch(url_marca(marca), {'lojas_permitidas': [self.loja_a.pk]}, format='json')
        self.assertEqual(list(marca.lojas_permitidas.values_list('pk', flat=True)), [self.loja_a.pk])

    def test_desativar_e_ativar_auditados(self):
        user = criar_usuario('ed', permissoes=ESCRITA, lojas=(self.loja_a,))
        cliente = cliente_logado(user)
        resposta = cliente.post(url_marca(self.livre, 'desativar'), {'motivo': 'Sem fornecedor'}, format='json')
        self.assertFalse(resposta.json()['ativo'])
        self.assertEqual(self.assertAuditado('marca_desativada', self.livre, usuario=user).motivo, 'Sem fornecedor')
        self.assertTrue(cliente.post(url_marca(self.livre, 'ativar')).json()['ativo'])
        self.assertAuditado('marca_ativada', self.livre)

    def test_desativar_exige_change_e_nao_aceita_get(self):
        so_ver = cliente_logado(criar_usuario('ver', permissoes=VER, lojas=(self.loja_a,)))
        self.assertErro(so_ver.post(url_marca(self.livre, 'desativar')), 403, 'proibido')
        self.assertErro(so_ver.get(url_marca(self.livre, 'desativar')), 405, 'metodo_nao_permitido')
        self.livre.refresh_from_db()
        self.assertTrue(self.livre.ativo)
