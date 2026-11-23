"""Base das views de contas a receber: escopo de pagamentos e 405 antes do 403."""
from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import exceptions

from vendas.models import ComprovanteParcela, Contato, Pagamento, Parcela, ProdutoVenda

from ..nucleo.views import BackofficeAPIView
from .constantes import PERMISSAO_GLOBAL_PAGAMENTOS


class MetodoNaoPermitidoAntesMixin:
    """Método sem handler responde 405 (e não 403 por não estar em `permissoes`).

    Usuário anônimo continua recebendo 401: a checagem vem depois da autenticação.
    """

    def check_permissions(self, request):
        metodo = request.method.lower()
        autenticado = bool(request.user and request.user.is_authenticated)
        if autenticado and (metodo not in self.http_method_names or not hasattr(self, metodo)):
            raise exceptions.MethodNotAllowed(request.method)
        super().check_permissions(request)


def prefetch_parcelas_completas() -> Prefetch:
    comprovantes = ComprovanteParcela.objects.select_related('criado_por').order_by('-criado_em', '-id')
    return Prefetch(
        'parcelas_pagamento',
        queryset=Parcela.objects.select_related('modificado_por')
        .prefetch_related(Prefetch('comprovantes', queryset=comprovantes))
        .order_by('numero_parcela', 'id'),
    )


def queryset_detalhe() -> QuerySet:
    return Pagamento.objects.select_related(
        'tipo_pagamento', 'loja', 'venda__loja',
        'venda__cliente__informacao_pessoal', 'venda__cliente__contato_adicional',
    ).prefetch_related(
        'statuses',
        Prefetch('venda__itens_venda', queryset=ProdutoVenda.objects.select_related('produto')),
        Prefetch('venda__cliente__contatos', queryset=Contato.objects.select_related('criado_por').order_by('-data', '-id')),
        prefetch_parcelas_completas(),
    )


class ContasAReceberBaseView(MetodoNaoPermitidoAntesMixin, BackofficeAPIView):
    """Escopo por `Pagamento.loja`; `can_view_all_payments` libera todas as lojas."""

    permissao_global_lojas = PERMISSAO_GLOBAL_PAGAMENTOS

    def pagamentos(self, queryset: QuerySet | None = None) -> QuerySet:
        return self.filtrar_por_lojas(queryset if queryset is not None else Pagamento.objects.all(), 'loja')

    def obter_pagamento(self, pk: int, queryset: QuerySet | None = None) -> Pagamento:
        return get_object_or_404(self.pagamentos(queryset), pk=pk)

    def obter_parcela(self, pk: int) -> Parcela:
        parcelas = self.filtrar_por_lojas(Parcela.objects.select_related('pagamento'), 'pagamento__loja')
        return get_object_or_404(parcelas, pk=pk)

    def obter_comprovante(self, pk: int) -> ComprovanteParcela:
        comprovantes = self.filtrar_por_lojas(
            ComprovanteParcela.objects.select_related('parcela__pagamento'), 'parcela__pagamento__loja',
        )
        return get_object_or_404(comprovantes, pk=pk)
