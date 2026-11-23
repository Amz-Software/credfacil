"""Provedor da busca global (Ctrl+K): solicitações por nome ou CPF."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response

from api.views.solicitacoes_regras import _filtro_busca_solicitacao
from backoffice_api.nucleo.views import BackofficeAPIView
from vendas.models import Cliente

from ..filtros import termo_de_busca
from ..regras import PERMISSAO_VER, PERMISSAO_VER_TODAS
from ..serializers.respostas import CreditoBuscaRespostaSerializer
from ..serializers.solicitacao_lista import CreditoBuscaItemSerializer
from .base import TAG, MetodoAntesDaPermissaoMixin

LIMITE_RESULTADOS = 8
TAMANHO_MINIMO_TERMO = 2


@extend_schema(
    tags=[TAG],
    parameters=[OpenApiParameter('termo', OpenApiTypes.STR, required=True, description='Nome ou CPF (mín. 2 caracteres).')],
    responses=CreditoBuscaRespostaSerializer,
)
class BuscaSolicitacoesView(MetodoAntesDaPermissaoMixin, BackofficeAPIView):
    permissao_global_lojas = PERMISSAO_VER_TODAS
    permissoes = {'GET': [PERMISSAO_VER]}

    def get(self, request):
        termo = termo_de_busca(request.query_params)
        if len(termo) < TAMANHO_MINIMO_TERMO:
            return Response({'resultados': []})
        base = Cliente.objects.filter(analise_credito__isnull=False).select_related('loja', 'analise_credito')
        clientes = (
            self.filtrar_por_lojas(base, 'loja')
            .filter(_filtro_busca_solicitacao(termo))
            .order_by('-analise_credito__data_analise', '-id')[:LIMITE_RESULTADOS]
        )
        return Response({'resultados': CreditoBuscaItemSerializer(clientes, many=True).data})
