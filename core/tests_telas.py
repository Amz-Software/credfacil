"""Rede de segurança das telas do backoffice.

1. Todo item do menu abre (HTTP 200) para um superusuário.
2. Todo nome de rota citado em templates e em código Python existe — evita
   link quebrado (NoReverseMatch) quando uma tela é removida ou renomeada.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from accounts.models import User
from vendas.models import Loja

BASE_DIR = Path(settings.BASE_DIR)
PASTAS_IGNORADAS = {'venv', '.venv', 'node_modules', 'staticfiles', 'mediafiles', 'sneat-template', '.git'}

URL_EM_TEMPLATE = re.compile(r"""\{%\s*url\s+['"]([\w:-]+)['"]""")
URL_EM_PYTHON = re.compile(
    r"""(?:reverse|reverse_lazy|redirect)\(\s*['"]([\w-]+:[\w-]+)['"]"""
    r"""|(?:data_view|url_name)["']?\s*[=:]\s*['"]([\w-]+:[\w-]+)['"]"""
)
ITEM_DE_MENU = re.compile(r'^\s*(?:\{)?\s*"url_name":\s*"([\w:-]+)"', re.MULTILINE)


def _arquivos(sufixo: str):
    for caminho in BASE_DIR.rglob(f'*{sufixo}'):
        if PASTAS_IGNORADAS.isdisjoint(caminho.relative_to(BASE_DIR).parts):
            yield caminho


def _rota_existe(nome: str) -> bool:
    try:
        reverse(nome)
    except NoReverseMatch as erro:
        mensagem = str(erro)
        # Rota existe, só faltaram os argumentos.
        return 'not a valid view function' not in mensagem and 'not a registered namespace' not in mensagem
    return True


def _sem_linhas_comentadas(texto: str) -> str:
    return '\n'.join(
        linha for linha in texto.splitlines() if not linha.lstrip().startswith('#')
    )


def _nomes_citados(padrao: re.Pattern, sufixo: str) -> dict[str, set[str]]:
    citados: dict[str, set[str]] = {}
    for caminho in _arquivos(sufixo):
        texto = caminho.read_text(encoding='utf-8', errors='ignore')
        if sufixo == '.py':
            texto = _sem_linhas_comentadas(texto)
        for grupos in padrao.findall(texto):
            nomes = grupos if isinstance(grupos, tuple) else (grupos,)
            for nome in filter(None, nomes):
                citados.setdefault(nome, set()).add(str(caminho.relative_to(BASE_DIR)))
    return citados


class RotasCitadasExistemTests(TestCase):
    def _assert_todas_existem(self, citados: dict[str, set[str]]):
        quebradas = {
            nome: sorted(arquivos)
            for nome, arquivos in sorted(citados.items())
            if not _rota_existe(nome)
        }
        self.assertEqual(quebradas, {}, f'Rotas citadas que não existem: {quebradas}')

    def test_rotas_citadas_em_templates_existem(self):
        self._assert_todas_existem(_nomes_citados(URL_EM_TEMPLATE, '.html'))

    def test_rotas_citadas_em_python_existem(self):
        self._assert_todas_existem(_nomes_citados(URL_EM_PYTHON, '.py'))


class LayoutAssetsTests(TestCase):
    """Bibliotecas do layout: só o que alguma tela usa, na ordem certa."""

    REMOVIDOS = (
        'apexcharts',
        'apex-charts',
        'dashboards-analytics',
        'typeahead',
        'fontawesome',
        'flag-icons',
        'cdn.jsdelivr.net/npm/chart.js"',
        'bootstrap-icons@1.10.5',
        'CSRF Token usado',
    )

    def _html_logado(self) -> str:
        loja = Loja.objects.create(nome='Loja Layout')
        admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='123456',
        )
        loja.usuarios.add(admin)
        self.client.force_login(admin)
        session = self.client.session
        session['loja_id'] = loja.id
        session.save()
        return self.client.get(reverse('vendas:guia')).content.decode()

    def test_layout_principal_nao_carrega_bibliotecas_sem_uso(self):
        html = self._html_logado()

        for trecho in self.REMOVIDOS:
            with self.subTest(trecho=trecho):
                self.assertNotIn(trecho, html)

    def test_layouts_nao_carregam_plugins_jquery_antes_do_jquery(self):
        html_logado = self._html_logado()
        self.client.logout()
        html_publico = self.client.get(reverse('vendas:consulta_pagamentos')).content.decode()

        for nome, html in (('base', html_logado), ('base_blank', html_publico)):
            with self.subTest(layout=nome):
                inicio_jquery = html.find('jquery.min.js')
                self.assertGreater(inicio_jquery, 0)
                self.assertNotIn('jquery.mask', html[:inicio_jquery])
                self.assertNotIn("$('", html[:inicio_jquery])

    def test_template_que_usa_mask_carrega_o_plugin(self):
        sem_plugin = []
        for caminho in _arquivos('.html'):
            texto = caminho.read_text(encoding='utf-8', errors='ignore')
            if '.mask(' in texto and 'jquery.mask' not in texto:
                sem_plugin.append(str(caminho.relative_to(BASE_DIR)))

        self.assertEqual(sem_plugin, [])

    def test_painel_customizador_do_tema_fica_oculto(self):
        config = BASE_DIR / 'static' / 'sneat-template' / 'assets' / 'js' / 'config.js'

        self.assertIn('displayCustomizer: false', config.read_text(encoding='utf-8'))


class MenuCatalogoTests(TestCase):
    def test_tipos_de_produto_aparece_no_menu_para_quem_tem_permissao(self):
        from django.contrib.auth.models import Permission

        loja = Loja.objects.create(nome='Loja Catálogo')
        user = User.objects.create_user(
            username='catalogo', email='catalogo@example.com', password='123456',
        )
        loja.usuarios.add(user)
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label__in=['vendas', 'produtos'],
            codename__in=['view_loja', 'view_tipoproduto'],
        ))
        self.client.force_login(user)
        session = self.client.session
        session['loja_id'] = loja.id
        session.save()

        response = self.client.get(reverse('vendas:guia'))

        self.assertContains(response, f'href="{reverse("produtos:tipos")}"')

    def test_telas_de_tipo_de_produto_abrem(self):
        from produtos.models import TipoProduto

        loja = Loja.objects.create(nome='Loja Catálogo')
        admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='123456',
        )
        loja.usuarios.add(admin)
        tipo = TipoProduto.objects.create(nome='Celular', numero_serial=True, loja=loja)
        self.client.force_login(admin)
        session = self.client.session
        session['loja_id'] = loja.id
        session.save()
        urls = [
            reverse('produtos:tipos'),
            reverse('produtos:tipo_create'),
            reverse('produtos:tipo_detail', args=[tipo.id]),
            reverse('produtos:tipo_update', args=[tipo.id]),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class MenuAbreTodasAsTelasTests(TestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Telas')
        self.admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='123456',
        )
        self.loja.usuarios.add(self.admin)
        self.client.force_login(self.admin)
        session = self.client.session
        session['loja_id'] = self.loja.id
        session.save()

    def test_todo_item_do_menu_responde_200(self):
        fonte = (BASE_DIR / 'core' / 'context_processors.py').read_text(encoding='utf-8')
        itens = ITEM_DE_MENU.findall(_sem_linhas_comentadas(fonte))
        self.assertGreater(len(itens), 10)

        for nome in itens:
            with self.subTest(rota=nome):
                response = self.client.get(reverse(nome))

                self.assertEqual(response.status_code, 200)
