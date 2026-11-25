"""Conversa no CRM a partir de contas a receber: telefones, conversa existente e aberturas da conta."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from backoffice_api.financeiro.constantes import PERMISSAO_GLOBAL_PAGAMENTOS
from crm.services import abertura_conta
from vendas.models import Pagamento

from ..base import CrmAPIView
from ..permissoes import ACESSO
from ..serializers.saida import AberturaContaSerializer
from . import TAGS


class ContaDoCrmMixin:
    """Mesmo escopo de lojas de contas a receber (`can_view_all_payments` libera todas)."""

    permissao_global_lojas = PERMISSAO_GLOBAL_PAGAMENTOS


def obter_pagamento_da_conta(view, pk: int) -> Pagamento:
    pagamentos = view.filtrar_por_lojas(Pagamento.objects.select_related('venda__cliente'), 'loja')
    return get_object_or_404(pagamentos, pk=pk)


class AberturaContaView(ContaDoCrmMixin, CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Conversar pelo CRM a partir da conta a receber',
                   description='Telefones do cliente com a conversa já existente (não cria), parcela em aberto '
                               'mais antiga e as aberturas com o texto preenchido.',
                   responses=AberturaContaSerializer)
    def get(self, request, pk: int):
        pagamento = obter_pagamento_da_conta(self, pk)
        return Response(AberturaContaSerializer(abertura_conta.contexto(pagamento)).data)
