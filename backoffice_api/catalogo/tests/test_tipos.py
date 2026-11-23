"""Tipos de produto: permissões, busca, criação, edição e campo `assistencia`."""
from django.contrib.auth.models import Permission

from backoffice_api.tests.fabricas import cliente_logado, criar_usuario
from produtos.models import TipoProduto

from .base import URL, CatalogoTestCase

URL_TIPOS = f'{URL}/tipos/'
TODAS = ('produtos.view_tipoproduto', 'produtos.add_tipoproduto', 'produtos.change_tipoproduto')


class TiposTests(CatalogoTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.celular = TipoProduto.objects.create(nome='Celular', numero_serial=True)
        cls.capa = TipoProduto.objects.create(nome='Capa')

    def test_sem_permissao_recebe_403(self):
        self.assertErro(cliente_logado(criar_usuario('semperm')).get(URL_TIPOS), 403, 'proibido')

    def test_lista_com_busca(self):
        cliente = cliente_logado(criar_usuario('ver', permissoes=('produtos.view_tipoproduto',)))
        resposta = cliente.get(URL_TIPOS, {'busca': 'cel'})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([t['nome'] for t in resposta.json()['results']], ['Celular'])
        self.assertEqual(cliente.get(f'{URL_TIPOS}{self.capa.pk}/').json()['nome'], 'Capa')

    def test_criar_e_editar(self):
        user = criar_usuario('cad', permissoes=TODAS)
        cliente = cliente_logado(user)
        resposta = cliente.post(URL_TIPOS, {'nome': 'Fone', 'numero_serial': False}, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        tipo = TipoProduto.objects.get(pk=resposta.json()['id'])
        self.assertEqual(tipo.criado_por, user)
        editado = cliente.patch(f'{URL_TIPOS}{tipo.pk}/', {'nome': 'Fone de ouvido'}, format='json')
        self.assertEqual(editado.json()['nome'], 'Fone de ouvido')

    def test_criar_exige_add_e_valida_nome(self):
        so_ver = cliente_logado(criar_usuario('ver', permissoes=('produtos.view_tipoproduto',)))
        self.assertErro(so_ver.post(URL_TIPOS, {'nome': 'X'}, format='json'), 403, 'proibido')
        cad = cliente_logado(criar_usuario('cad', permissoes=TODAS))
        self.assertErro(cad.post(URL_TIPOS, {'nome': ''}, format='json'), 400, 'validacao', 'nome')

    def test_assistencia_so_com_permissao(self):
        sem = cliente_logado(criar_usuario('cad', permissoes=TODAS))
        corpo = {'nome': 'Peça', 'assistencia': True}
        self.assertErro(sem.post(URL_TIPOS, corpo, format='json'), 400, 'validacao', 'assistencia')
        com_user = criar_usuario('tec', permissoes=TODAS)
        com_user.user_permissions.add(Permission.objects.filter(codename='view_assistencia').first())
        resposta = cliente_logado(com_user).post(URL_TIPOS, corpo, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertTrue(resposta.json()['assistencia'])

    def test_sem_exclusao_nem_put(self):
        cliente = cliente_logado(criar_usuario('cad', permissoes=TODAS))
        self.assertErro(cliente.delete(f'{URL_TIPOS}{self.capa.pk}/'), 405, 'metodo_nao_permitido')
        self.assertErro(cliente.put(f'{URL_TIPOS}{self.capa.pk}/', {'nome': 'X'}, format='json'), 405,
                        'metodo_nao_permitido')
        self.assertTrue(TipoProduto.objects.filter(pk=self.capa.pk).exists())
