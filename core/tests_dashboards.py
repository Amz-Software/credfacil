"""Telas de indicadores: componentes padrão, sem CSS/JS inline e sem cores fixas."""
import re

from core.tests_interface import BASE_DIR, BackofficeTestCase

COR_HEX = re.compile(r'#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b')
SCRIPT_INLINE = re.compile(r'<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>')


def fonte(caminho: str) -> str:
    return (BASE_DIR / caminho).read_text(encoding='utf-8')


class TemplateLimpoMixin:
    def assert_template_limpo(self, caminho: str):
        texto = fonte(caminho)
        self.assertNaoTem('<style', texto)
        self.assertEqual(SCRIPT_INLINE.findall(texto), [], f'{caminho} tem <script> inline')
        self.assertEqual(COR_HEX.findall(texto), [], f'{caminho} tem cores fixas')


class PaginaInicialTests(TemplateLimpoMixin, BackofficeTestCase):
    def test_indicadores_usam_kpi_card_e_grafico_vem_de_arquivo(self):
        html = self.html('vendas:index')

        self.assertGreaterEqual(html.count('kpi-card'), 13)
        self.assertTem('css/dashboard.css', html)
        self.assertTem('js/index-grafico.js', html)
        self.assertTem('id="parcelasChart" data-dados="', html)
        self.assertTem('ipix-hero', html)
        self.assertTem('Olá, Maria', html)

    def test_template_sem_css_js_inline_nem_hex(self):
        self.assert_template_limpo('vendas/templates/index.html')


class DashboardDeGraficosTests(TemplateLimpoMixin, BackofficeTestCase):
    def test_indicadores_usam_kpi_card_e_graficos_vem_de_arquivo(self):
        html = self.html('vendas:grafico')

        self.assertGreaterEqual(html.count('kpi-card'), 22)
        self.assertTem('css/dashboard.css', html)
        self.assertTem('js/dash-graficos.js', html)
        self.assertTem('id="graficoLojas" class="grafico-dash" data-dados="', html)

    def test_template_sem_css_js_inline_nem_hex(self):
        self.assert_template_limpo('vendas/templates/dash/index.html')


class SolicitacoesDeCreditoTelaTests(TemplateLimpoMixin, BackofficeTestCase):
    def test_lista_carrega_css_e_js_proprios_com_dados_por_atributo(self):
        html = self.html('vendas:cliente_list')

        self.assertTem('css/cliente-list.css', html)
        self.assertTem('js/cliente-list.js', html)
        self.assertTem('data-kpis-url="/caixas/kpis/"', html)
        self.assertTem('id="statusChoices"', html)

    def test_template_sem_css_js_inline_nem_hex(self):
        self.assert_template_limpo('vendas/templates/cliente/cliente_list.html')


class DetalheDaLojaTelaTests(TemplateLimpoMixin, BackofficeTestCase):
    def test_kpis_por_componente_e_js_em_arquivo(self):
        html = self.html('vendas:loja_detail', self.loja.pk)

        self.assertEqual(html.count('kpi-card'), 3)
        self.assertTem('js/loja-detail.js', html)
        self.assertTem(f'data-loja-id="{self.loja.pk}"', html)
        self.assertTem('Nenhuma venda encontrada', html)

    def test_template_sem_css_js_inline_nem_hex(self):
        self.assert_template_limpo('vendas/templates/loja/loja_detail.html')


class CoresPorTokenTests(TemplateLimpoMixin, BackofficeTestCase):
    """Telas usam tokens --ipix-*; só impressos/PDF (sem o CSS do tema) e o
    meta theme-color mantêm cor literal."""

    IMPRESSOS = ('pdf', 'folha', 'contrato', 'carne', 'report_', 'relatorio_solicitacoes',
                 'relatorio_serasa', 'notificacao_bo_preview', 'foto_celular', 'relatorio_parcelas')

    def test_templates_de_tela_sem_cor_hex(self):
        com_hex = []
        for caminho in BASE_DIR.rglob('*.html'):
            relativo = str(caminho.relative_to(BASE_DIR))
            if any(p in relativo for p in ('venv', 'sneat-template', 'staticfiles', 'crm/')):
                continue
            if any(p in caminho.name for p in self.IMPRESSOS):
                continue
            texto = re.sub(r'<meta name="theme-color"[^>]*>', '', caminho.read_text(encoding='utf-8'))
            if COR_HEX.search(texto):
                com_hex.append(relativo)
        self.assertEqual(com_hex, [])
