"""Lojas: lista, detalhe com KPIs e calendário, criação, edição, arquivos e QR code."""
from datetime import date

from django.db.models import Exists, OuterRef, Q, Sum
from django.http import FileResponse
from django.utils.dateparse import parse_date
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from financeiro.models import Repasse
from vendas.services.lojas import replicar_qr_code_aplicativo

from ...nucleo.erros import NAO_ENCONTRADO_RECURSO, VALIDACAO, ErroBackoffice
from ...nucleo.permissoes import EmGrupo
from ..base import TAGS, LojasBaseView
from ..serializers import LojaDetalheSerializer, LojaEscritaSerializer, LojaListaSerializer, VendaDoPeriodoSerializer
from ..servicos import calendario_do_detalhe, calendario_por_loja, kpis_da_loja, situacao_repasse, vendas_do_periodo

FILTROS_REPASSE = ('pendente', 'sem_pendente')
CAMPOS_RELACAO = ('usuarios', 'gerentes', 'produtos_bloqueados')
PARAMETROS_PERIODO = [
    OpenApiParameter('data_inicio', OpenApiTypes.DATE),
    OpenApiParameter('data_fim', OpenApiTypes.DATE),
]


def ler_periodo(params) -> tuple:
    datas = []
    for campo in ('data_inicio', 'data_fim'):
        valor = params.get(campo) or ''
        data = parse_date(valor) if valor else None
        if valor and data is None:
            raise ErroBackoffice('Revise os filtros informados.', codigo=VALIDACAO,
                                 campos={campo: ['Use o formato AAAA-MM-DD.']})
        datas.append(data)
    return tuple(datas)


def _ids(loja, campo: str) -> list[int]:
    return sorted(getattr(loja, campo).values_list('pk', flat=True))


def resumo_da_loja(loja) -> dict:
    """Retrato para a auditoria (campos simples + ids das relações)."""
    simples = {campo: str(getattr(loja, campo)) for campo in LojaEscritaSerializer.Meta.fields
               if campo not in CAMPOS_RELACAO + ('logo_loja', 'qr_code_aplicativo', 'contrato')}
    return {**simples, **{campo: _ids(loja, campo) for campo in CAMPOS_RELACAO}}


def diferencas(antes: dict, depois: dict) -> dict:
    return {campo: {'antes': antes.get(campo), 'depois': valor}
            for campo, valor in depois.items() if antes.get(campo) != valor}


@extend_schema(tags=TAGS)
class LojasView(LojasBaseView):
    permissoes = {'GET': ['vendas.view_loja'], 'POST': ['vendas.add_loja']}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        parameters=[OpenApiParameter('busca', str), OpenApiParameter('repasse', str, enum=list(FILTROS_REPASSE))],
        responses=LojaListaSerializer(many=True),
    )
    def get(self, request):
        lojas = self.lojas_visiveis()
        busca = (request.query_params.get('busca') or '').strip()
        if busca:
            lojas = lojas.filter(Q(nome__icontains=busca) | Q(cnpj__icontains=busca))
        filtro = request.query_params.get('repasse')
        if filtro and filtro not in FILTROS_REPASSE:
            raise ErroBackoffice('Revise os filtros informados.', codigo=VALIDACAO,
                                 campos={'repasse': ['Use pendente ou sem_pendente.']})
        if filtro:
            # `Loja.objects.com_repasse_pendente()` conta também as linhas sem repasse
            # (Count de Case com default 0) e devolve todas as lojas; aqui a regra é aplicada com Exists.
            pendente = Exists(Repasse.objects.filter(
                loja=OuterRef('pk'), status='pendente', data__date__lte=date.today(),
            ))
            lojas = lojas.filter(pendente) if filtro == 'pendente' else lojas.exclude(pendente)
        paginador = self.pagination_class()
        pagina = paginador.paginate_queryset(lojas.order_by('nome', 'id'), request, view=self)
        calendario = calendario_por_loja(pagina)
        repasses = {pk: {'situacao': situacao_repasse(periodos, atrasados), 'atrasados': atrasados}
                    for pk, (periodos, atrasados) in calendario.items()}
        dados = LojaListaSerializer(pagina, many=True, context={'repasses': repasses}).data
        return paginador.get_paginated_response(dados)

    @extend_schema(request=LojaEscritaSerializer, responses={201: LojaDetalheSerializer})
    def post(self, request):
        entrada = LojaEscritaSerializer(data=request.data, context={'request': request})
        entrada.is_valid(raise_exception=True)
        loja = entrada.save()
        self.auditar('loja_criada', objeto=loja, dados=resumo_da_loja(loja))
        return Response(LojaDetalheSerializer(loja).data, status=201)


@extend_schema(tags=TAGS)
class LojaDetalheView(LojasBaseView):
    permissoes = {'GET': ['vendas.view_loja'], 'PATCH': ['vendas.change_loja']}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(parameters=PARAMETROS_PERIODO, responses={200: OpenApiTypes.OBJECT})
    def get(self, request, pk: int):
        loja = self.obter_loja(pk)
        data_inicio, data_fim = ler_periodo(request.query_params)
        pode_ver_repasse = request.user.is_superuser or request.user.has_perm('financeiro.view_repasse')
        return Response({
            'loja': LojaDetalheSerializer(loja).data,
            'periodo': {'data_inicio': data_inicio, 'data_fim': data_fim},
            'kpis': kpis_da_loja(loja, data_inicio, data_fim),
            'calendario_repasses': calendario_do_detalhe(loja, data_inicio, data_fim) if pode_ver_repasse else None,
        })

    @extend_schema(request=LojaEscritaSerializer, responses=LojaDetalheSerializer)
    def patch(self, request, pk: int):
        loja = self.obter_loja(pk)
        antes = resumo_da_loja(loja)
        entrada = LojaEscritaSerializer(loja, data=request.data, partial=True, context={'request': request})
        entrada.is_valid(raise_exception=True)
        loja = entrada.save()
        mudancas = diferencas(antes, resumo_da_loja(loja))
        arquivos = [c for c in ('logo_loja', 'qr_code_aplicativo', 'contrato') if c in entrada.validated_data]
        if mudancas or arquivos:
            self.auditar('loja_alterada', objeto=loja, dados={'alteracoes': mudancas, 'arquivos_e_contrato': arquivos})
        return Response(LojaDetalheSerializer(loja).data)


@extend_schema(tags=TAGS)
class LojaVendasView(LojasBaseView):
    """Vendas da loja no período, com paginação própria (`page`, `page_size`)."""

    permissoes = {'GET': ['vendas.view_loja']}

    @extend_schema(parameters=PARAMETROS_PERIODO, responses=VendaDoPeriodoSerializer(many=True))
    def get(self, request, pk: int):
        loja = self.obter_loja(pk)
        data_inicio, data_fim = ler_periodo(request.query_params)
        vendas = (
            vendas_do_periodo(loja, data_inicio, data_fim)
            .select_related('cliente')
            .annotate(valor_total=Sum('pagamentos__valor', filter=Q(pagamentos__tipo_pagamento__nao_contabilizar=False)))
            .order_by('-data_venda', '-id')
        )
        return self.paginar(vendas, VendaDoPeriodoSerializer)


class _ArquivoDaLojaView(LojasBaseView):
    permissoes = {'GET': ['vendas.view_loja']}
    campo = ''

    @extend_schema(tags=TAGS, responses={(200, 'image/*'): OpenApiTypes.BINARY})
    def get(self, request, pk: int):
        arquivo = getattr(self.obter_loja(pk), self.campo)
        if not arquivo:
            raise ErroBackoffice('A loja não tem este arquivo.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
        try:
            aberto = arquivo.open('rb')
        except (ValueError, FileNotFoundError, OSError):
            raise ErroBackoffice('Arquivo não encontrado no servidor.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
        resposta = FileResponse(aberto, filename=arquivo.name.rsplit('/', 1)[-1])
        resposta['X-Content-Type-Options'] = 'nosniff'
        resposta['Cache-Control'] = 'private, max-age=300'
        return resposta


class LojaLogoView(_ArquivoDaLojaView):
    campo = 'logo_loja'


class LojaQrCodeView(_ArquivoDaLojaView):
    campo = 'qr_code_aplicativo'


@extend_schema(tags=TAGS)
class ReplicarQrCodeView(LojasBaseView):
    permissoes = {'POST': ['vendas.change_loja', EmGrupo('ADMINISTRADOR')]}

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, pk: int):
        loja = self.obter_loja(pk)
        total = replicar_qr_code_aplicativo(loja)
        self.auditar('loja_qrcode_replicado', objeto=loja, dados={'lojas_alteradas': total})
        return Response({'lojas_alteradas': total,
                         'mensagem': 'QR Code e código do aplicativo replicados para as outras lojas.'})
