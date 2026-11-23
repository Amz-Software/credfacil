"""Item da fila de análise (lista, busca e retorno das ações)."""
from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from ..regras import ETAPAS, STATUS_EM_ANALISE, etapa_da_analise, mascarar_cpf
from .comum import DINHEIRO, CreditoLojaRefSerializer, CreditoProdutoRefSerializer, CreditoUsuarioRefSerializer

CENTAVOS = Decimal('0.01')


def entrada_da_analise(analise) -> Decimal:
    """Entrada efetiva: a informada pelo operador ou a mínima do produto (regra da geração da venda)."""
    if analise.entrada_informada is not None:
        return analise.entrada_informada
    return analise.produto.entrada_cliente


def numero_parcelas(analise) -> int | None:
    try:
        return int(analise.numero_parcelas)
    except (TypeError, ValueError):
        return None


class CreditoSolicitacaoListaSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text='Id da solicitação (é o id do cliente).')
    analise_id = serializers.IntegerField(source='analise_credito.id')
    cliente = serializers.CharField(source='nome')
    cpf = serializers.SerializerMethodField(help_text='CPF mascarado (***.456.789-**).')
    loja = CreditoLojaRefSerializer(allow_null=True)
    vendedor = CreditoUsuarioRefSerializer(source='analise_credito.criado_por', allow_null=True)
    produto = CreditoProdutoRefSerializer(source='analise_credito.produto')
    valor = serializers.DecimalField(source='analise_credito.produto.valor', allow_null=True, **DINHEIRO)
    entrada = serializers.SerializerMethodField()
    numero_parcelas = serializers.SerializerMethodField()
    data_pagamento = serializers.CharField(source='analise_credito.data_pagamento', allow_null=True)
    status = serializers.CharField(source='analise_credito.status')
    status_rotulo = serializers.CharField(source='analise_credito.get_status_display')
    status_app = serializers.CharField(source='analise_credito.status_aplicativo')
    status_app_rotulo = serializers.CharField(source='analise_credito.get_status_aplicativo_display')
    etapa = serializers.SerializerMethodField()
    etapa_rotulo = serializers.SerializerMethodField()
    is_iphone = serializers.BooleanField(source='analise_credito.produto.is_iphone')
    icloud_configurado_vendedor = serializers.BooleanField(source='analise_credito.icloud_configurado_vendedor')
    icloud_confirmado_analista = serializers.BooleanField(source='analise_credito.icloud_confirmado_analista')
    tem_imei = serializers.SerializerMethodField()
    analise_online = serializers.BooleanField(source='analise_credito.analise_online')
    segunda_compra = serializers.BooleanField(source='analise_credito.segunda_compra')
    venda_gerada = serializers.SerializerMethodField()
    venda_id = serializers.IntegerField(source='analise_credito.venda_id', allow_null=True)
    criado_em = serializers.DateTimeField(source='analise_credito.data_analise')
    tempo_espera_segundos = serializers.SerializerMethodField(
        help_text='Segundos desde a criação, só enquanto a solicitação está em análise.'
    )

    def get_cpf(self, cliente) -> str:
        return mascarar_cpf(cliente.cpf)

    def get_entrada(self, cliente) -> str:
        return str(entrada_da_analise(cliente.analise_credito).quantize(CENTAVOS))

    def get_numero_parcelas(self, cliente) -> int | None:
        return numero_parcelas(cliente.analise_credito)

    def get_etapa(self, cliente) -> str:
        return etapa_da_analise(cliente.analise_credito)

    def get_etapa_rotulo(self, cliente) -> str:
        return ETAPAS[etapa_da_analise(cliente.analise_credito)]

    def get_tem_imei(self, cliente) -> bool:
        return cliente.analise_credito.imei_id is not None

    def get_venda_gerada(self, cliente) -> bool:
        return cliente.analise_credito.venda_id is not None

    def get_tempo_espera_segundos(self, cliente) -> int | None:
        analise = cliente.analise_credito
        if analise.status != STATUS_EM_ANALISE or not analise.data_analise:
            return None
        return max(int((timezone.now() - analise.data_analise).total_seconds()), 0)


class CreditoBuscaItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    cliente = serializers.CharField(source='nome')
    cpf = serializers.SerializerMethodField()
    status = serializers.CharField(source='analise_credito.status')
    status_rotulo = serializers.CharField(source='analise_credito.get_status_display')
    loja = serializers.CharField(source='loja.nome', allow_null=True, default=None)

    def get_cpf(self, cliente) -> str:
        return mascarar_cpf(cliente.cpf)
