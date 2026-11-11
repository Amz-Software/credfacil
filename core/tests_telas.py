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
