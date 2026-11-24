"""Painel do backoffice: resumo por papel, dashboard de gráficos e PDF do dashboard."""
from django.template.loader import get_template
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from backoffice_api.nucleo.escopo import filtrar_por_lojas
from backoffice_api.nucleo.papel import tamanho_pagina
from backoffice_api.nucleo.views import BackofficeAPIView
from backoffice_api.relatorios.pdf import EntregaDeArquivoMixin, resposta_pdf
from vendas.models import AnaliseCreditoCliente
from vendas.services.kpis import PERMISSAO_VER_TODAS_ANALISES

from .serializers import FiltrosGraficosSerializer, GraficosSerializer, ResumoPainelSerializer
from .servicos.carteira import Periodo
from .servicos.graficos import calcular_graficos, formatar_graficos
from .servicos.relatorio_pdf import TEMPLATE_PDF, contexto_relatorio_dashboard
from .servicos.resumo import (
    atalhos_do_usuario,
    kpis_carteira,
    parcelas_de_contas_a_receber,
    resumo_fila_credito,
    resumo_inadimplencia,
)

TAG = 'bo-painel'
PERMISSAO_KPIS = 'vendas.can_view_your_dashboard'
PERMISSAO_FILA = 'vendas.view_cliente'
PERMISSAO_INADIMPLENCIA = 'vendas.view_pagamento'
PERMISSAO_TODOS_PAGAMENTOS = 'vendas.can_view_all_payments'
PERMISSAO_GRAFICOS = 'vendas.can_view_all_dashboard'
PERMISSAO_PDF_DASHBOARD = 'vendas.can_generate_dashboard_report'

PARAMETROS_GRAFICOS = [
    OpenApiParameter('loja', OpenApiTypes.INT, description='Id da loja (dentro do escopo).'),
    OpenApiParameter('data_inicio', OpenApiTypes.DATE, description='AAAA-MM-DD.'),
    OpenApiParameter('data_fim', OpenApiTypes.DATE, description='AAAA-MM-DD.'),
    OpenApiParameter('comodato', OpenApiTypes.BOOL, description='true = só vendas de comodato; false = só as comuns.'),
]


class PainelResumoView(BackofficeAPIView):
    """Página inicial: cada bloco só vem preenchido para quem tem a permissão dele."""

    permissoes = {'GET': []}

    @extend_schema(tags=[TAG], summary='Resumo do painel por papel', responses=ResumoPainelSerializer)
    def get(self, request):
        lojas = self.lojas()  # valida X-Loja (400/403) antes de montar os blocos
        user = request.user
        lista = list(lojas[:2])
        dados = {
            'loja': {'id': lista[0].pk, 'nome': lista[0].nome} if len(lista) == 1 else None,
            'quantidade_lojas': lojas.count(),
            'kpis': kpis_carteira(lojas) if user.has_perm(PERMISSAO_KPIS) else None,
            'analise': self._fila(request) if user.has_perm(PERMISSAO_FILA) else None,
            'financeiro': self._inadimplencia(request) if user.has_perm(PERMISSAO_INADIMPLENCIA) else None,
            'atalhos': atalhos_do_usuario(user),
        }
        return Response(ResumoPainelSerializer(dados).data)

    @staticmethod
    def _fila(request) -> dict:
        analises = filtrar_por_lojas(AnaliseCreditoCliente.objects.all(), request, 'loja', PERMISSAO_VER_TODAS_ANALISES)
        return resumo_fila_credito(analises)

    @staticmethod
    def _inadimplencia(request) -> dict:
        parcelas = filtrar_por_lojas(
            parcelas_de_contas_a_receber(), request, 'pagamento__loja', PERMISSAO_TODOS_PAGAMENTOS,
        )
        return resumo_inadimplencia(parcelas)


class _FiltroGraficosMixin:
    """Lojas efetivas (escopo ∩ X-Loja ∩ `?loja`), período e filtro de comodato validados."""

    def filtros(self):
        lojas = self.lojas()
        filtro = FiltrosGraficosSerializer(data=self.request.query_params, lojas=lojas)
        filtro.is_valid(raise_exception=True)
        dados = filtro.validated_data
        loja = dados.get('loja')
        recorte = lojas.filter(pk=loja.pk) if loja else lojas
        periodo = Periodo(dados.get('data_inicio'), dados.get('data_fim'))
        return lojas, recorte, loja, periodo, dados.get('comodato')


class PainelGraficosView(_FiltroGraficosMixin, BackofficeAPIView):
    permissoes = {'GET': [PERMISSAO_GRAFICOS]}
    permissao_global_lojas = PERMISSAO_GRAFICOS

    @extend_schema(
        tags=[TAG], summary='Dashboard de gráficos', parameters=PARAMETROS_GRAFICOS, responses=GraficosSerializer,
    )
    def get(self, request):
        lojas, recorte, loja, periodo, comodato = self.filtros()
        resultado = calcular_graficos(recorte, periodo, incluir_mensal=recorte.count() == 1, comodato=comodato)
        dados = {
            'filtros': {
                'loja': loja.pk if loja else None, 'data_inicio': periodo.inicio, 'data_fim': periodo.fim,
                'comodato': comodato,
            },
            'lojas_disponiveis': [{'id': pk, 'nome': nome} for pk, nome in lojas.order_by('nome').values_list('pk', 'nome')],
            **formatar_graficos(resultado),
        }
        return Response(GraficosSerializer(dados).data)


class PainelGraficosPdfView(EntregaDeArquivoMixin, _FiltroGraficosMixin, BackofficeAPIView):
    permissoes = {'GET': [PERMISSAO_PDF_DASHBOARD]}
    permissao_global_lojas = PERMISSAO_PDF_DASHBOARD

    @extend_schema(
        tags=[TAG],
        summary='PDF do dashboard (mesmo conteúdo do relatório atual)',
        parameters=PARAMETROS_GRAFICOS,
        responses={(200, 'application/pdf'): OpenApiResponse(OpenApiTypes.BINARY, description='Arquivo PDF.')},
    )
    def get(self, request):
        pagina = tamanho_pagina(request.query_params)
        _, recorte, loja, periodo, comodato = self.filtros()
        contexto = {
            **contexto_relatorio_dashboard(recorte, periodo, request.user, comodato=comodato),
            'tamanho_pagina': pagina,
        }
        resposta = resposta_pdf(get_template(TEMPLATE_PDF).render(contexto), 'relatorio_dashboard')
        self.auditar(
            'relatorio_gerado',
            descricao='Relatório PDF do dashboard',
            dados={
                'relatorio': 'painel_graficos',
                'formato': 'pdf',
                'filtros': {
                    'loja': loja.pk if loja else None,
                    'data_inicio': periodo.inicio.isoformat() if periodo.inicio else None,
                    'data_fim': periodo.fim.isoformat() if periodo.fim else None,
                    'comodato': comodato,
                },
                'lojas': sorted(recorte.values_list('pk', flat=True)),
                'clientes_listados': len(contexto['clientes_quitados_lista']),
            },
        )
        return resposta
