"""Contatos de cobrança do cliente e notificação extrajudicial para B.O."""
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.response import Response

from vendas.models import Contato, Pagamento, ProdutoVenda
from vendas.services.erros import ErroDeNegocio

from ...nucleo.permissoes import EmGrupo
from ..base import ContasAReceberBaseView
from ..bo import dados_da_previa, gerar_pdf_bo, referencias_padrao
from ..constantes import GRUPOS_ANALISTA_ADMIN
from ..entradas import BoPdfEntradaSerializer, ContatoEntradaSerializer
from ..resumo import tem_parcela_vencida_em_aberto
from ..serializers import ContatoSerializer

TAGS = ['bo-financeiro']
PERMISSOES_BO = [EmGrupo(*GRUPOS_ANALISTA_ADMIN), 'financeiro.add_notificacaobo']
MENSAGEM_SEM_PARCELA_VENCIDA = 'Não há parcela vencida em aberto para gerar o BO.'


@extend_schema(tags=TAGS)
class ContatoCriarView(ContasAReceberBaseView):
    permissoes = {'POST': ['vendas.add_contato']}

    @extend_schema(request=ContatoEntradaSerializer, responses={201: ContatoSerializer})
    def post(self, request, pk: int):
        pagamento = self.obter_pagamento(pk, Pagamento.objects.select_related('venda__cliente'))
        entrada = ContatoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        contato = Contato(cliente=pagamento.venda.cliente, loja=pagamento.loja, **entrada.validated_data)
        contato.save(user=request.user)
        return Response(ContatoSerializer(contato).data, status=201)


@extend_schema(tags=TAGS)
class ContatoEditarView(ContasAReceberBaseView):
    permissoes = {'PATCH': ['vendas.change_contato']}

    @extend_schema(request=ContatoEntradaSerializer, responses=ContatoSerializer)
    def patch(self, request, pk: int, contato_pk: int):
        pagamento = self.obter_pagamento(pk, Pagamento.objects.select_related('venda'))
        contato = get_object_or_404(
            Contato.objects.select_related('criado_por'), pk=contato_pk, cliente_id=pagamento.venda.cliente_id,
        )
        entrada = ContatoEntradaSerializer(contato, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        for campo, valor in entrada.validated_data.items():
            setattr(contato, campo, valor)
        contato.save(user=request.user)
        return Response(ContatoSerializer(contato).data)


class BoBaseView(ContasAReceberBaseView):
    """Exige parcela vencida em aberto, como a tela Django."""

    def pagamento_com_parcela_vencida(self, pk: int) -> Pagamento:
        queryset = Pagamento.objects.select_related(
            'venda__cliente__informacao_pessoal', 'venda__cliente__contato_adicional', 'venda__loja',
        ).prefetch_related(
            Prefetch('venda__itens_venda', queryset=ProdutoVenda.objects.select_related('produto')),
            'parcelas_pagamento',
        )
        pagamento = self.obter_pagamento(pk, queryset)
        if not tem_parcela_vencida_em_aberto(list(pagamento.parcelas_pagamento.all()), timezone.localdate()):
            raise ErroDeNegocio(MENSAGEM_SEM_PARCELA_VENCIDA)
        return pagamento


@extend_schema(tags=TAGS)
class BoPreviaView(BoBaseView):
    permissoes = {'GET': PERMISSOES_BO}

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request, pk: int):
        return Response(dados_da_previa(self.pagamento_com_parcela_vencida(pk)))


@extend_schema(tags=TAGS)
class BoPdfView(BoBaseView):
    permissoes = {'POST': PERMISSOES_BO}

    @extend_schema(request=BoPdfEntradaSerializer, responses={(200, 'application/pdf'): OpenApiTypes.BINARY})
    def post(self, request, pk: int):
        pagamento = self.pagamento_com_parcela_vencida(pk)
        entrada = BoPdfEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        referencias = entrada.validated_data['referencias_personais'].strip() or referencias_padrao(
            pagamento.venda.cliente
        )
        pdf = gerar_pdf_bo(pagamento, referencias, request)
        self.auditar('bo_gerado', objeto=pagamento, dados={'referencias_editadas': bool(
            entrada.validated_data['referencias_personais'].strip()
        )})
        resposta = HttpResponse(pdf, content_type='application/pdf')
        resposta['Content-Disposition'] = f'inline; filename="notificacao_bo_pagamento_{pagamento.pk}.pdf"'
        resposta['Cache-Control'] = 'private, no-store'
        return resposta
