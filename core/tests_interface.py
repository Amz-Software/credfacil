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


def _criar_pagamento(loja, vendedor):
    from datetime import date, timedelta
    from decimal import Decimal

    from vendas.models import Cliente, ComprovantesCliente, Pagamento, Parcela, TipoPagamento, Venda

    cliente = Cliente.objects.create(
        nome='Cliente <script>x</script>', telefone='91999999999', cpf='12345678900',
        nascimento=date(1990, 1, 1), rg='123', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém',
        comprovantes=ComprovantesCliente.objects.create(),
    )
    venda = Venda.objects.create(
        cliente=cliente, vendedor=vendedor, loja=loja, repasse_logista=Decimal('100.00'),
    )
    tipo = TipoPagamento.objects.get_or_create(nome='IPX', defaults={'parcelas': True, 'caixa': False})[0]
    pagamento = Pagamento.objects.create(
        venda=venda, tipo_pagamento=tipo, valor=Decimal('1000.00'),
        parcelas=10, loja=loja, data_primeira_parcela=date.today(),
    )
    Parcela.objects.create(
        pagamento=pagamento, numero_parcela=1, valor=Decimal('100.00'),
        data_vencimento=date.today() - timedelta(days=30), pago=False, loja=loja,
    )
    return pagamento


class ContasAReceberTelasTests(BackofficeTestCase):
    def setUp(self):
        super().setUp()
        self.pagamento = _criar_pagamento(self.loja, self.user)

    def test_detalhe_pede_confirmacao_nas_situacoes_destrutivas(self):
        html = self.html('financeiro:contas_a_receber_update', self.pagamento.id)

        self.assertNaoTem('onchange="this.form.submit()"', html)
        for campo in ('sitBo', 'sitRoubo', 'sitBloqueado', 'sitDesativado', 'sitDevolucao', 'sitSemConexao'):
            with self.subTest(campo=campo):
                inicio = html.index(f'id="{campo}"')
                tag = html[inicio:html.index('>', inicio)]
                self.assertTem('data-auto-submit', tag)
                self.assertTem('data-confirmar-ligar=', tag)
                self.assertTem('data-confirmar-desligar=', tag)
        self.assertTem('id="confirmActionModal"', html)
        self.assertTem('js/contas-a-receber-detail.js', html)
        self.assertTem('css/contas-a-receber.css', html)

    def test_detalhe_sem_css_e_js_inline(self):
        html = self.html('financeiro:contas_a_receber_update', self.pagamento.id)

        self.assertNaoTem('<style>', html)
        self.assertNaoTem('function setupAddParcela', html)
        self.assertNaoTem('class="bi ', html)
        self.assertTem('data-arquivo="conta_', html)

    def test_lista_usa_css_compartilhado_e_tokens(self):
        html = self.html('financeiro:contas_a_receber_list')

        self.assertTem('css/contas-a-receber.css', html)
        self.assertNaoTem('<style>', html)
        self.assertNaoTem('style="background:#', html)


def _criar_solicitacao(loja):
    from datetime import date

    from produtos.models import Produto
    from vendas.models import AnaliseCreditoCliente, Cliente, ComprovantesCliente, ContatoAdicional, InformacaoPessoal

    cliente = Cliente.objects.create(
        nome='Joana Lima', telefone='91999999999', cpf='12345678901',
        nascimento=date(1990, 1, 1), rg='123', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(),
        contato_adicional=ContatoAdicional.objects.create(),
        informacao_pessoal=InformacaoPessoal.objects.create(),
    )
    produto = Produto.objects.create(nome='Galaxy A15', loja=loja)
    AnaliseCreditoCliente.objects.create(cliente=cliente, produto=produto, loja=loja)
    return cliente


class EdicaoComErrosTests(BackofficeTestCase):
    def setUp(self):
        super().setUp()
        # Os widgets do django-select2 gravam no cache "select2" (Redis em
        # produção); nos testes usamos memória local.
        from unittest import mock

        from django.core.cache.backends.locmem import LocMemCache

        patcher = mock.patch('django_select2.forms.cache', LocMemCache('select2-testes', {}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_editar_venda_mostra_erros_do_formulario(self):
        pagamento = _criar_pagamento(self.loja, self.user)
        venda = pagamento.venda

        response = self.client.post(reverse('vendas:venda_update', args=[venda.id]), {
            'cliente': '', 'vendedor': '', 'observacao': '',
            'itens_venda-TOTAL_FORMS': '0', 'itens_venda-INITIAL_FORMS': '0',
            'pagamentos-TOTAL_FORMS': '0', 'pagamentos-INITIAL_FORMS': '0',
        })
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTem('Corrija os campos abaixo:', html)
        self.assertTem('invalid-feedback d-block', html)
        self.assertTem('js/venda-edit.js', html)
        self.assertNaoTem('alert(', html)

    def test_edicao_especial_usa_o_mesmo_modulo_js(self):
        pagamento = _criar_pagamento(self.loja, self.user)

        html = self.html('vendas:venda_edicao_especial', pagamento.venda.id)

        self.assertTem('js/venda-edit.js', html)

    def test_imei_telefone_mostra_erros_e_tira_js_inline(self):
        cliente = _criar_solicitacao(self.loja)

        response = self.client.post(
            reverse('vendas:cliente_update_imei_telefone', args=[cliente.id]),
            {'telefone': '', 'produto': ''},
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTem('Corrija os campos abaixo:', html)
        self.assertTem('id="clienteFormDados"', html)
        self.assertTem('js/form-cliente-imei-telefone.js', html)
        self.assertTem('css/form-cliente.css', html)
        self.assertNaoTem('<style>', html)
        self.assertNaoTem('JSON.parse(', html)


class FormularioSolicitacaoTests(BackofficeTestCase):
    def setUp(self):
        super().setUp()
        from unittest import mock

        from django.core.cache.backends.locmem import LocMemCache

        patcher = mock.patch('django_select2.forms.cache', LocMemCache('select2-testes', {}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nova_solicitacao_sem_css_e_js_inline(self):
        from produtos.models import Marca

        Marca.objects.create(nome='Samsung', loja=self.loja)

        html = self.html('vendas:cliente_create')

        self.assertTem('id="formClienteDados"', html)
        self.assertTem('js/form-cliente.js', html)
        self.assertTem('css/form-cliente.css', html)
        self.assertNaoTem('<style>', html)
        self.assertNaoTem('JSON.parse(', html)
        self.assertTem('Nova Solicitação de Crédito · IPIX', ' '.join(html.split()))

    def test_editar_solicitacao_passa_parcelamento_salvo_por_data_attribute(self):
        from produtos.models import Marca

        Marca.objects.create(nome='Samsung', loja=self.loja)
        cliente = _criar_solicitacao(self.loja)
        cliente.analise_credito.numero_parcelas = '6'
        cliente.analise_credito.save()

        html = self.html('vendas:cliente_update', cliente.id)

        self.assertTem('data-parcelas-salvas="6"', html)
        self.assertTem(f'data-produto-salvo-id="{cliente.analise_credito.produto_id}"', html)


class SemDepuracaoNoFrontTests(TestCase):
    def test_templates_e_scripts_nao_tem_console_log(self):
        com_log = [
            str(caminho.relative_to(BASE_DIR))
            for caminho in _templates_e_scripts()
            if 'console.log(' in caminho.read_text(encoding='utf-8', errors='ignore')
            and 'accounts/templates/login' not in str(caminho)
        ]

        self.assertEqual(com_log, [])

    def test_templates_nao_usam_alert_nem_confirm_nativos(self):
        nativo = re.compile(r'(?<![\w.])(?:window\.)?(?:alert|confirm)\(')
        com_nativo = [
            str(caminho.relative_to(BASE_DIR))
            for caminho in _templates_e_scripts()
            if caminho.name != 'confirm-action.js'
            and nativo.search(caminho.read_text(encoding='utf-8', errors='ignore'))
        ]

        self.assertEqual(com_nativo, [])


ITEM_DO_MENU_COM_ROTULO = re.compile(r'"label":\s*"([^"]+)",\s*\n\s*"url_name":\s*"([\w:-]+)"')
# Telas cujo template pertence a outra frente de trabalho (ainda "Editar Perfil").
TITULOS_PENDENTES = {'accounts:my_profile_update'}


class TitulosTests(BackofficeTestCase):
    def test_titulo_de_cada_tela_do_menu_e_o_nome_do_menu(self):
        fonte = (BASE_DIR / 'core' / 'context_processors.py').read_text(encoding='utf-8')
        itens = ITEM_DO_MENU_COM_ROTULO.findall(fonte)
        self.assertGreater(len(itens), 15)

        for rotulo, nome in itens:
            if nome in TITULOS_PENDENTES or nome.startswith('crm:'):
                continue
            with self.subTest(rota=nome):
                html = self.html(nome)
                titulo = ' '.join(re.search(r'<title>(.*?)</title>', html, re.S).group(1).split())
                self.assertEqual(titulo, f'{rotulo} · IPIX')


class IconesETabelasTests(TestCase):
    def test_nenhum_template_usa_bootstrap_icons(self):
        com_bi = [
            str(caminho.relative_to(BASE_DIR))
            for caminho in BASE_DIR.rglob('*.html')
            if PASTAS_IGNORADAS.isdisjoint(caminho.relative_to(BASE_DIR).parts)
            and re.search(r'class="bi |bootstrap-icons', caminho.read_text(encoding='utf-8', errors='ignore'))
        ]

        self.assertEqual(com_bi, [])

    def test_tabelas_de_tela_ficam_em_table_responsive(self):
        impressao = re.compile(r'pdf|folha|relatorio|contrato|carne|report|print|admin/')
        sem_wrapper = []
        for caminho in BASE_DIR.rglob('*.html'):
            relativo = str(caminho.relative_to(BASE_DIR))
            if not PASTAS_IGNORADAS.isdisjoint(caminho.relative_to(BASE_DIR).parts) or impressao.search(relativo):
                continue
            texto = caminho.read_text(encoding='utf-8', errors='ignore')
            if '<table' in texto and 'table-responsive' not in texto and 'card_table_open' not in texto:
                sem_wrapper.append(relativo)

        self.assertEqual(sem_wrapper, [])
