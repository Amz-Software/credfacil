"""Central de relatórios: catálogo, prévia paginada, PDF (WeasyPrint) e Excel de parcelas."""
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

from backoffice_api.nucleo.erros import REGRA_DE_NEGOCIO, ErroBackoffice
from backoffice_api.nucleo.escopo import filtrar_por_lojas, lojas_da_requisicao
from backoffice_api.nucleo.papel import tamanho_pagina
from backoffice_api.nucleo.views import BackofficeAPIView
from crm.permissoes import pode_acessar

from .definicoes import RELATORIOS, DefinicaoRelatorio
from .excel_parcelas import gerar_planilha
from .filtros import descrever_filtros, filtros_para_auditoria
from .pdf import TIPO_XLSX, EntregaDeArquivoMixin, nome_arquivo, renderizar_template_local, resposta_arquivo, resposta_pdf
from .serializers import RelatorioCatalogoSerializer, previa_serializer
from .servicos.comum import EscopoRelatorio

TAG = 'bo-relatorios'
LIMITE_LINHAS_PDF = 3000
ACAO_AUDITORIA = 'relatorio_gerado'


def pode_gerar_algum(request, view) -> bool:
    return any(request.user.has_perm(d.permissao) for d in RELATORIOS.values())


def _enderecos(definicao: DefinicaoRelatorio) -> dict:
    return {
        formato: reverse(f'backoffice_api:relatorios:{definicao.id}_{formato}')
        for formato in definicao.formatos
    }


class CatalogoRelatoriosView(BackofficeAPIView):
    """Relatórios que o usuário pode gerar, com os filtros para montar os formulários."""

    permissoes = {'GET': [pode_gerar_algum]}

    @extend_schema(tags=[TAG], summary='Catálogo de relatórios', responses=RelatorioCatalogoSerializer(many=True))
    def get(self, request):
        itens = []
        for definicao in RELATORIOS.values():
            if not request.user.has_perm(definicao.permissao):
                continue
            lojas = lojas_da_requisicao(request, definicao.permissao_global_lojas)
            itens.append({
                'id': definicao.id,
                'titulo': definicao.titulo,
                'descricao': definicao.descricao,
                'formatos': list(definicao.formatos),
                'filtros': descrever_filtros(definicao.filtros(lojas=lojas)),
                'enderecos': _enderecos(definicao),
            })
        return Response(RelatorioCatalogoSerializer(itens, many=True).data)


class _RelatorioBase(BackofficeAPIView):
    """Valida os filtros dentro do escopo de lojas do relatório e monta a consulta."""

    relatorio: DefinicaoRelatorio | None = None

    def preparar(self):
        definicao = self.relatorio
        filtro = definicao.filtros(data=self.request.query_params, lojas=self.lojas())
        filtro.is_valid(raise_exception=True)
        validados = filtro.validated_data
        escopo = EscopoRelatorio(
            lojas_escolhidas=tuple(validados.get('lojas') or ()),
            aplicar_escopo=lambda qs, campo: filtrar_por_lojas(qs, self.request, campo, definicao.permissao_global_lojas),
            ve_crm=pode_acessar(self.request.user),
        )
        consulta = definicao.servico.consultar(validados, escopo)
        return validados, consulta

    def registrar(self, formato: str, validados: dict, quantidade: int) -> None:
        self.auditar(
            ACAO_AUDITORIA,
            descricao=f'{self.relatorio.titulo} ({formato})',
            dados={
                'relatorio': self.relatorio.id,
                'formato': formato,
                'filtros': filtros_para_auditoria(validados),
                'registros': quantidade,
            },
        )


class RelatorioPreviaView(_RelatorioBase):
    def get(self, request):
        validados, consulta = self.preparar()
        servico = self.relatorio.servico
        totais = servico.totais(consulta, validados)
        paginador = self.pagination_class()
        pagina = paginador.paginate_queryset(consulta, request, view=self)
        linhas = self.relatorio.serializer_linha(servico.linhas(pagina), many=True).data
        resposta = paginador.get_paginated_response(linhas)
        resposta.data['totais'] = self.relatorio.serializer_totais(totais).data
        resposta.data['filtros'] = filtros_para_auditoria(validados)
        self.registrar('previa', validados, paginador.page.paginator.count)
        return resposta


class RelatorioPdfView(EntregaDeArquivoMixin, _RelatorioBase):
    def get(self, request):
        pagina = tamanho_pagina(request.query_params)
        validados, consulta = self.preparar()
        quantidade = consulta.count()
        if quantidade > LIMITE_LINHAS_PDF:
            raise ErroBackoffice(
                f'O PDF tem {quantidade} registros (máximo {LIMITE_LINHAS_PDF}). Refine os filtros.',
                codigo=REGRA_DE_NEGOCIO, status_http=422,
            )
        servico = self.relatorio.servico
        contexto = {
            'titulo': self.relatorio.titulo,
            'linhas': servico.linhas(consulta),
            'totais': servico.totais(consulta, validados),
            'filtros': validados,
            'lojas_nomes': [loja.nome for loja in validados.get('lojas') or []],
            'usuario': request.user,
            'tamanho_pagina': pagina,
            **self.relatorio.contexto_pdf(validados),
        }
        resposta = resposta_pdf(renderizar_template_local(self.relatorio.template_pdf, contexto), f'relatorio_{self.relatorio.id}')
        self.registrar('pdf', validados, quantidade)
        return resposta


class RelatorioParcelasExcelView(EntregaDeArquivoMixin, _RelatorioBase):
    relatorio = RELATORIOS['parcelas']
    permissoes = {'GET': [RELATORIOS['parcelas'].permissao]}
    permissao_global_lojas = RELATORIOS['parcelas'].permissao_global_lojas

    @extend_schema(
        tags=[TAG], summary='Relatório de parcelas em Excel (grade colorida)', parameters=[RELATORIOS['parcelas'].filtros],
        responses={(200, TIPO_XLSX): OpenApiResponse(OpenApiTypes.BINARY, description='Planilha .xlsx.')},
    )
    def get(self, request):
        validados, consulta = self.preparar()
        linhas = self.relatorio.servico.linhas(consulta)
        resposta = resposta_arquivo(gerar_planilha(linhas), TIPO_XLSX, nome_arquivo('relatorio_parcelas', 'xlsx'))
        self.registrar('excel', validados, len(linhas))
        return resposta


def _classe(base, definicao: DefinicaoRelatorio, sufixo: str):
    nome = ''.join(parte.capitalize() for parte in definicao.id.split('_')) + sufixo

    def get(self, request):  # função própria: o esquema de cada relatório não vaza para os outros
        return base.get(self, request)

    return type(nome, (base,), {
        'get': get,
        'relatorio': definicao,
        'permissoes': {'GET': [definicao.permissao]},
        'permissao_global_lojas': definicao.permissao_global_lojas,
    })


def views_do_relatorio(definicao: DefinicaoRelatorio):
    """Uma view de prévia e uma de PDF por relatório, cada uma com o esquema dos seus filtros."""
    previa = _classe(RelatorioPreviaView, definicao, 'PreviaView')
    resposta_previa = previa_serializer(
        f'Previa{previa.__name__.removesuffix("PreviaView")}', definicao.serializer_linha, definicao.serializer_totais,
    )
    previa.get = extend_schema(
        tags=[TAG], summary=f'{definicao.titulo}: prévia paginada', parameters=[definicao.filtros],
        responses=resposta_previa,
    )(previa.get)
    pdf = _classe(RelatorioPdfView, definicao, 'PdfView')
    pdf.get = extend_schema(
        tags=[TAG], summary=f'{definicao.titulo}: PDF', parameters=[definicao.filtros],
        responses={(200, 'application/pdf'): OpenApiResponse(OpenApiTypes.BINARY, description='Arquivo PDF.')},
    )(pdf.get)
    return previa, pdf
