"""Opções do formulário de loja (`GET opcoes/`)."""
from django.test import TestCase

from backoffice_api.tests.fabricas import cliente_logado, criar_usuario
from produtos.models import Produto

from .fabricas import URL_BASE

URL = f'{URL_BASE}opcoes/'


class OpcoesFormularioTests(TestCase):
    def test_exige_add_ou_change_loja(self):
        sem = cliente_logado(criar_usuario('sem', permissoes=('vendas.view_loja',)))
        self.assertEqual(sem.get(URL).status_code, 403)
        com = cliente_logado(criar_usuario('com', permissoes=('vendas.change_loja',)))
        self.assertEqual(com.get(URL).status_code, 200)

    def test_lista_usuarios_e_produtos_ativos_e_flag_restrita(self):
        criar_usuario('inativo', ativo=False)
        Produto.objects.create(nome='Galaxy', ativo=True)
        Produto.objects.create(nome='Antigo', ativo=False)
        dados = cliente_logado(criar_usuario('ger', permissoes=('vendas.add_loja',))).get(URL).json()
        nomes_usuarios = {u['nome'] for u in dados['usuarios']}
        self.assertIn('Ger', nomes_usuarios)
        self.assertNotIn('Inativo', nomes_usuarios)
        self.assertEqual([p['nome'] for p in dados['produtos']], ['Galaxy'])
        self.assertFalse(dados['pode_editar_campos_restritos'])
        admin = cliente_logado(criar_usuario('adm', permissoes=('vendas.add_loja',), grupos=('ADMINISTRADOR',)))
        self.assertTrue(admin.get(URL).json()['pode_editar_campos_restritos'])

    def test_post_405(self):
        com = cliente_logado(criar_usuario('com', permissoes=('vendas.add_loja',)))
        self.assertEqual(com.post(URL, {}).status_code, 405)
