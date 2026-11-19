"""Interface do backoffice: layout base, tema, feedback e telas principais.

Não há navegador nos testes; aqui renderizamos as telas e verificamos o HTML
e os arquivos estáticos que o layout carrega.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.contrib.auth.models import Group
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from vendas.models import Loja

BASE_DIR = Path(settings.BASE_DIR)
STATIC_DIR = BASE_DIR / 'static'
PASTAS_IGNORADAS = {'venv', '.venv', 'node_modules', 'staticfiles', 'mediafiles', 'sneat-template', '.git', 'crm'}


def _templates_e_scripts():
    for sufixo in ('*.html', '*.js'):
        for caminho in BASE_DIR.rglob(sufixo):
            if PASTAS_IGNORADAS.isdisjoint(caminho.relative_to(BASE_DIR).parts):
                yield caminho


def _ler_static(*partes) -> str:
    return STATIC_DIR.joinpath(*partes).read_text(encoding='utf-8')


class TrechoMixin:
    """assertIn/NotIn sem despejar a página inteira na falha."""

    def assertTem(self, trecho, html):
        self.assertTrue(trecho in html, f'Trecho ausente: {trecho!r}')

    def assertNaoTem(self, trecho, html):
        self.assertFalse(trecho in html, f'Trecho não deveria aparecer: {trecho!r}')


class BackofficeTestCase(TrechoMixin, TestCase):
    """Superusuário logado com uma loja na sessão."""

    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Interface')
        self.user = User.objects.create_superuser(
            username='maria', email='maria@example.com', password='123456',
            first_name='Maria', last_name='Souza',
        )
        self.loja.usuarios.add(self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session['loja_id'] = self.loja.id
        session.save()

    def html(self, nome_rota, *args, **params) -> str:
        response = self.client.get(reverse(nome_rota, args=args), params)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class LayoutBaseTests(BackofficeTestCase):
    def test_estilos_e_scripts_do_layout_vem_de_arquivos_estaticos(self):
        html = self.html('vendas:guia')

        self.assertTem('css/base.css', html)
        self.assertTem('js/notificacoes.js', html)
        self.assertTem('js/base.js', html)
        self.assertTem('js/toasts.js', html)
        self.assertNaoTem('.whatsapp-float {', html)
        self.assertNaoTem('new WebSocket(', html)

    def test_viewport_permite_zoom(self):
        html = self.html('vendas:guia')

        self.assertNaoTem('user-scalable=no', html)
        self.assertNaoTem('maximum-scale=1.0', html)
        self.assertTem('<meta name="viewport" content="width=device-width, initial-scale=1.0" />', html)

    def test_formularios_usam_16px_em_telas_pequenas(self):
        css = _ler_static('css', 'base.css')

        self.assertRegex(css, r'@media \(max-width: 767\.98px\)[^}]*\.form-control[^}]*font-size: 16px')

    def test_titulo_da_pagina_termina_com_ipix(self):
        html = self.html('vendas:guia')

        titulo = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
        self.assertEqual(' '.join(titulo.split()), 'Guia do Sistema · IPIX')

    def test_seletor_de_tema_em_portugues(self):
        html = self.html('vendas:guia')

        for rotulo in ('Claro', 'Escuro', 'Sistema'):
            with self.subTest(rotulo=rotulo):
                self.assertTem(f'</i>{rotulo}</span>', html)
        for rotulo in ('>Light<', '>Dark<', '>System<'):
            self.assertNaoTem(rotulo, html.replace('</i>', '>'))

    def test_um_unico_conjunto_de_icones(self):
        html = self.html('vendas:guia')

        self.assertNaoTem('bootstrap-icons', html)
        self.assertNaoTem('class="bi ', html)
        self.assertTem('boxicons.css', html)


class MenuDoUsuarioTests(BackofficeTestCase):
    def test_menu_do_usuario_tem_links_reais_e_iniciais(self):
        html = self.html('vendas:guia')

        self.assertTem(f'href="{reverse("accounts:my_profile_update")}"', html)
        self.assertTem(f'href="{reverse("accounts:password_change")}"', html)
        self.assertTem('<span class="avatar-iniciais" aria-hidden="true">MS</span>', html)
        self.assertNaoTem('avatars/1.png', html)
        self.assertNaoTem('Settings', html)

    def test_menu_mostra_nome_do_grupo(self):
        self.user.groups.add(Group.objects.create(name='ANALISTA'))

        html = self.html('vendas:guia')

        self.assertTem('<small class="text-muted">Analista</small>', html)
        self.assertNaoTem('>User<', html)


class NotificacoesSemXssTests(TrechoMixin, TestCase):
    def test_script_de_notificacoes_nao_injeta_html(self):
        js = _ler_static('js', 'notificacoes.js')

        self.assertNaoTem('innerHTML', js)
        self.assertNaoTem('insertAdjacentHTML', js)
        self.assertNaoTem('console.', js)
        self.assertTem('textContent', js)


class ToastsTests(TrechoMixin, TestCase):
    def test_mensagens_do_django_viram_toasts(self):
        mensagens = [
            Message(constants.ERROR, 'Falha <b>ao salvar</b>'),
            Message(constants.SUCCESS, 'Tudo certo'),
        ]

        html = render_to_string('snippets/toast_messages.html', {'messages': mensagens})

        self.assertTem('id="ipixToastContainer"', html)
        self.assertTem('text-bg-danger', html)
        self.assertTem('text-bg-success', html)
        self.assertTem('Falha &lt;b&gt;ao salvar&lt;/b&gt;', html)
        # Erro fica até fechar; sucesso some sozinho.
        self.assertEqual(html.count('data-bs-autohide="false"'), 1)
        self.assertEqual(html.count('data-bs-autohide="true"'), 1)

    def test_layout_inclui_toasts_no_lugar_dos_alerts(self):
        base = (BASE_DIR / 'templates' / 'base.html').read_text(encoding='utf-8')

        self.assertTem("{% include 'snippets/toast_messages.html' %}", base)
        self.assertNaoTem('alert_messages.html', base)


class TemaTests(TrechoMixin, TestCase):
    def test_modo_escuro_nao_troca_o_primario_para_azul(self):
        self.assertFalse((STATIC_DIR / 'css' / 'dark-mode-improvements.css').exists())
        tema = _ler_static('css', 'ipix-theme.css')
        bloco_escuro = tema[tema.index('6. Modo escuro'):]

        self.assertTem('--bs-primary: #FDC600', bloco_escuro)
        self.assertNaoTem('#8ea7ff', tema.lower())

    def test_modo_escuro_redefine_os_tokens_de_superficie(self):
        tema = _ler_static('css', 'ipix-theme.css')
        bloco_escuro = tema[tema.index('6. Modo escuro'):]

        for token in ('--ipix-body-bg', '--ipix-surface', '--ipix-border', '--ipix-text', '--ipix-heading'):
            with self.subTest(token=token):
                self.assertTem(f'{token}:', bloco_escuro)
