"""Item ativo da sidebar: detalhe/edição destacam o item da listagem correspondente."""
from django.test import RequestFactory, TestCase

from accounts.models import User
from core.context_processors import menu_items


class MenuItemAtivoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', email='a@a.com', password='x')

    def _ativos(self, caminho):
        request = RequestFactory().get(caminho)
        request.user = self.admin
        ativos = []
        for itens in menu_items(request)['menu_items'].values():
            for item in itens:
                if item.get('active'):
                    ativos.append(item['label'])
                ativos.extend(f"{item['label']} > {sub['label']}" for sub in item.get('sub_items', []) if sub.get('active'))
        return ativos

    def test_pagina_de_edicao_destaca_a_listagem(self):
        self.assertEqual(self._ativos('/clientes/cliente_editar/1/'), ['Solicitações de Crédito'])

    def test_raiz_so_na_pagina_inicial(self):
        self.assertEqual(self._ativos('/'), ['Página Inicial'])
        self.assertEqual(self._ativos('/rota-sem-menu/'), [])

    def test_vence_a_url_mais_especifica(self):
        self.assertEqual(self._ativos('/vendas/relatorio/'), ['Relatórios', 'Relatórios > Relatório de Vendas'])
        self.assertEqual(self._ativos('/vendas/detail/7/'), ['Vendas'])
        self.assertEqual(
            self._ativos('/relatorio/contas-a-receber/avancado'),
            ['Contas a Receber', 'Contas a Receber > Relatório de Situações'],
        )

    def test_url_sem_barra_final_nao_casa_por_texto(self):
        self.assertEqual(self._ativos('/financeiro/contas-a-receber/3'),
                         ['Contas a Receber', 'Contas a Receber > Contas a Receber'])
        self.assertEqual(self._ativos('/financeiro/contas-a-receberx'), [])
