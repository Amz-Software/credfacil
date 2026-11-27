"""Aba Contatos do detalhe da conta ligada ao CRM: painel, tentativas e notas."""
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from backoffice_api.crm.permissoes import ACESSO
from vendas.models import Pagamento

from ...nucleo.permissoes import EmGrupo
from .. import contato_crm
from ..base import ContasAReceberBaseView
from ..constantes import GRUPOS_ANALISTA_ADMIN
from ..entradas import NotaCrmEntradaSerializer, TentativaCrmEntradaSerializer
from ..serializers_contato_crm import PainelContatoSerializer

TAGS = ['bo-financeiro']
VER_CONTA = [EmGrupo(*GRUPOS_ANALISTA_ADMIN), 'vendas.view_pagamento']
STATUS_CRIADO = 201


class ContatoCrmBaseView(ContasAReceberBaseView):
    def cliente_da_conta(self, pk: int):
        return self.obter_pagamento(pk, Pagamento.objects.select_related('venda__cliente')).venda.cliente

    def resposta_painel(self, cliente, status: int = 200) -> Response:
        dados = contato_crm.painel(cliente, self.request.user)
        return Response(PainelContatoSerializer(dados).data, status=status)


@extend_schema(tags=TAGS)
class ContatoCrmView(ContatoCrmBaseView):
    permissoes = {'GET': VER_CONTA}

    @extend_schema(summary='Painel de contato: telefones, status e linha do tempo (manual, CRM e notas)',
                   responses=PainelContatoSerializer)
    def get(self, request, pk: int):
        return self.resposta_painel(self.cliente_da_conta(pk))


@extend_schema(tags=TAGS)
class TentativaCrmView(ContatoCrmBaseView):
    permissoes = {'POST': VER_CONTA + ACESSO}

    @extend_schema(summary='Registrar tentativa de contato no CRM', request=TentativaCrmEntradaSerializer,
                   responses={STATUS_CRIADO: PainelContatoSerializer})
    def post(self, request, pk: int):
        cliente = self.cliente_da_conta(pk)
        entrada = TentativaCrmEntradaSerializer(data=request.data, context={'cliente': cliente})
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        contato_crm.registrar_tentativa(dados['telefone'], request.user, dados)
        return self.resposta_painel(cliente, STATUS_CRIADO)


@extend_schema(tags=TAGS)
class NotaCrmView(ContatoCrmBaseView):
    permissoes = {'POST': VER_CONTA + ACESSO}

    @extend_schema(summary='Nota interna na conversa mais recente do cliente no CRM',
                   request=NotaCrmEntradaSerializer, responses={STATUS_CRIADO: PainelContatoSerializer})
    def post(self, request, pk: int):
        cliente = self.cliente_da_conta(pk)
        entrada = NotaCrmEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        contato_crm.criar_nota(cliente, request.user, entrada.validated_data['texto'])
        return self.resposta_painel(cliente, STATUS_CRIADO)
