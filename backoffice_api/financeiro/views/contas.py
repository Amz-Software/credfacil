"""Contas a receber: lista, detalhe, desconto, situações e quitação."""
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from vendas.models import Parcela, ProdutoVenda, StatusPagamento

from ...nucleo.permissoes import EmGrupo
from ..base import ContasAReceberBaseView, queryset_detalhe
from ..constantes import GRUPOS_ANALISTA_ADMIN, PERMISSAO_FILTRO_LOJA
from ..entradas import DescontoEntradaSerializer, QuitacaoEntradaSerializer, SituacaoEntradaSerializer
from ..filtros import base_contas_a_receber, filtrar_contas
from ..historico import historico_do_pagamento
from ..serializers import ContaAReceberDetalheSerializer, ContaAReceberListaSerializer, StatusPagamentoSerializer
from ..servicos import alterar_desconto, alterar_situacao, alterar_status_pagamento, confirmar_quitacao

TAGS = ['bo-financeiro']
SO_ADMIN = EmGrupo('ADMINISTRADOR')
MENSAGEM_FORCAR_SO_ADMIN = 'Só administrador quita sem o cliente ter informado o pagamento.'
PARAMETROS_LISTA = [
    OpenApiParameter('busca', str, description='Nome, CPF, observação de contato ou nº do pagamento'),
    OpenApiParameter('status', str, enum=['no_prazo', 'atrasado', 'quitado', 'pendente']),
    OpenApiParameter('loja', int, description='Só com vendas.can_view_all_stores'),
    OpenApiParameter('status_pagamento', int, many=True),
    OpenApiParameter('situacao', str, many=True, description='Situações ligadas (E): bloqueado, desativado, '
                     'flag_atrasado (cobrança), sem_contato, mais_prazo, pagamento_efetuado, ...'),
    OpenApiParameter('ordenar', str, description='criado_em, id, valor, cliente, proximo_vencimento (com - para desc.)'),
]


class DetalheMixin:
    """Monta a resposta do detalhe (também devolvida pelas ações sobre o pagamento)."""

    def resposta_detalhe(self, pk: int, status: int = 200) -> Response:
        pagamento = self.obter_pagamento(pk, queryset_detalhe())
        contexto = {
            'request': self.request,
            'todos_status': list(StatusPagamento.objects.order_by('nome')),
            'historico': historico_do_pagamento(pagamento),
        }
        return Response(ContaAReceberDetalheSerializer(pagamento, context=contexto).data, status=status)


@extend_schema(tags=TAGS)
class ContasAReceberListaView(ContasAReceberBaseView):
    permissoes = {'GET': ['vendas.view_pagamento']}

    @extend_schema(parameters=PARAMETROS_LISTA, responses=ContaAReceberListaSerializer(many=True))
    def get(self, request):
        user = request.user
        queryset = filtrar_contas(
            self.pagamentos(base_contas_a_receber()),
            request.query_params,
            pode_filtrar_loja=user.is_superuser or user.has_perm(PERMISSAO_FILTRO_LOJA),
        ).select_related('venda__cliente', 'venda__loja').prefetch_related(
            'statuses',
            Prefetch('venda__itens_venda', queryset=ProdutoVenda.objects.select_related('produto')),
            Prefetch('parcelas_pagamento', queryset=Parcela.objects.order_by('numero_parcela', 'id')),
        )
        return self.paginar(queryset, ContaAReceberListaSerializer)


@extend_schema(tags=TAGS)
class ContaAReceberDetalheView(DetalheMixin, ContasAReceberBaseView):
    permissoes = {
        'GET': [EmGrupo(*GRUPOS_ANALISTA_ADMIN), 'vendas.view_pagamento'],
        'PATCH': [EmGrupo(*GRUPOS_ANALISTA_ADMIN), 'vendas.change_pagamento'],
    }

    @extend_schema(responses=ContaAReceberDetalheSerializer)
    def get(self, request, pk: int):
        return self.resposta_detalhe(pk)

    @extend_schema(request=DescontoEntradaSerializer, responses=ContaAReceberDetalheSerializer)
    def patch(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        entrada = DescontoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        mudanca = alterar_desconto(pagamento, entrada.validated_data['porcentagem_desconto'], request.user)
        if mudanca.mudou:
            self.auditar(
                'pagamento_desconto_alterado', objeto=pagamento, motivo=entrada.validated_data.get('motivo', ''),
                dados={'antes': str(mudanca.antes), 'depois': str(mudanca.depois)},
            )
        return self.resposta_detalhe(pk)


@extend_schema(tags=TAGS)
class SituacoesView(DetalheMixin, ContasAReceberBaseView):
    """Substitui os 11 toggles por GET da tela Django (mesma regra, agora por POST e auditado)."""

    permissoes = {'POST': ['vendas.change_pagamento']}

    @extend_schema(request=SituacaoEntradaSerializer, responses=ContaAReceberDetalheSerializer)
    def post(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        entrada = SituacaoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        if dados.get('situacao'):
            mudanca = alterar_situacao(pagamento, dados['situacao'], dados.get('ativo'), request.user)
            acao, detalhe = 'pagamento_situacao_alterada', {'situacao': dados['situacao']}
        else:
            status = get_object_or_404(StatusPagamento, pk=dados['status_pagamento'])
            mudanca = alterar_status_pagamento(pagamento, status, dados.get('ativo'))
            acao, detalhe = 'pagamento_status_alterado', {'status_pagamento': status.pk, 'nome': status.nome}
        if mudanca.mudou:
            self.auditar(acao, objeto=pagamento, motivo=dados.get('motivo', ''),
                         dados={**detalhe, 'antes': mudanca.antes, 'depois': mudanca.depois})
        return self.resposta_detalhe(pk)


@extend_schema(tags=TAGS)
class QuitarView(DetalheMixin, ContasAReceberBaseView):
    permissoes = {'POST': ['vendas.can_confirm_quitacao']}

    @extend_schema(request=QuitacaoEntradaSerializer, responses=ContaAReceberDetalheSerializer)
    def post(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        entrada = QuitacaoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        forcar = entrada.validated_data['forcar']
        if forcar and not SO_ADMIN.avaliar(request.user):
            raise PermissionDenied(MENSAGEM_FORCAR_SO_ADMIN)
        resultado = confirmar_quitacao(pagamento, request.user, forcar=forcar)
        if resultado is not None:  # None = já estava quitada (repetição): nada a auditar
            self.auditar('pagamento_quitado', objeto=pagamento, motivo=entrada.validated_data['motivo'],
                         dados=resultado)
        return self.resposta_detalhe(pk)


@extend_schema(tags=TAGS)
class StatusPagamentoListaView(ContasAReceberBaseView):
    """Opções de status de pagamento (filtro da lista e etiquetas do detalhe)."""

    permissoes = {'GET': ['vendas.view_pagamento']}
    pagination_class = None

    @extend_schema(responses=StatusPagamentoSerializer(many=True))
    def get(self, request):
        return Response(StatusPagamentoSerializer(StatusPagamento.objects.order_by('nome'), many=True).data)
