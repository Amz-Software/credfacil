"""Serializers dos disparos manuais de cobrança (entrada e saída)."""
from rest_framework import serializers

from crm.models import DisparoCobranca, ItemDisparo
from crm.services.central_cobranca import disparos

from .base import CrmSerializer
from .cobranca import (ClienteMiniCobrancaSerializer, ModeloMiniSerializer, MotivoContagemSerializer,
                       ParcelaMiniSerializer)
from .saida import UsuarioMiniSerializer


class DisparoCriarSerializer(CrmSerializer):
    modelo = serializers.IntegerField(min_value=1, help_text='id da mensagem de abertura (GET cobranca/modelos/).')
    atraso_min = serializers.IntegerField(required=False, min_value=1, max_value=disparos.MAX_DIAS_ATRASO)
    atraso_max = serializers.IntegerField(required=False, min_value=1, max_value=disparos.MAX_DIAS_ATRASO)
    vencimento_data = serializers.DateField(required=False)
    vencimento_dia = serializers.ChoiceField(choices=list(disparos.DIAS_VENCIMENTO), required=False,
                                             help_text='Próximo vencimento no dia 1, 10 ou 20 (hoje conta).')
    parcelas = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, allow_empty=False,
                                     max_length=disparos.MAX_PARCELAS_LISTA)

    def validate(self, dados: dict) -> dict:
        criterios = (('atraso', ('atraso_min', 'atraso_max')), ('vencimento_data', ('vencimento_data',)),
                     ('vencimento_dia', ('vencimento_dia',)), ('parcelas', ('parcelas',)))
        usados = [c for c, campos in criterios if any(campo in dados for campo in campos)]
        if len(usados) != 1:
            raise serializers.ValidationError('Escolha um único critério: atraso, data de vencimento, dia do '
                                              'vencimento ou lista de parcelas.')
        if usados[0] == 'atraso':
            self._validar_atraso(dados)
        return dados

    @staticmethod
    def _validar_atraso(dados: dict) -> None:
        if 'atraso_min' not in dados or 'atraso_max' not in dados:
            raise serializers.ValidationError({'atraso_max': ['Informe o atraso mínimo e o máximo (em dias).']})
        if dados['atraso_min'] > dados['atraso_max']:
            raise serializers.ValidationError({'atraso_min': ['O atraso mínimo não pode passar do máximo.']})


class DisparosQuerySerializer(CrmSerializer):
    status = serializers.ChoiceField(choices=DisparoCobranca.Status.values, required=False, allow_blank=True,
                                     help_text='Sem filtro: todos menos as prévias.')
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1)


class DestinatariosQuerySerializer(CrmSerializer):
    situacao = serializers.ChoiceField(choices=ItemDisparo.Situacao.values, required=False, allow_blank=True)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1)


class ModeloDisparoSerializer(CrmSerializer):
    id = serializers.IntegerField()
    titulo = serializers.CharField()
    texto = serializers.CharField(help_text='Texto com os marcadores {nome}, {valor}, {vencimento}.')
    marcadores = serializers.ListField(child=serializers.CharField())
    nome_meta = serializers.CharField()


class DisparoItemSerializer(CrmSerializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=DisparoCobranca.Status.values)
    status_display = serializers.CharField()
    modelo = ModeloMiniSerializer()
    filtros = serializers.DictField()
    criado_por = UsuarioMiniSerializer(allow_null=True)
    criado_em = serializers.DateTimeField()
    confirmado_em = serializers.DateTimeField(allow_null=True)
    concluido_em = serializers.DateTimeField(allow_null=True)
    total = serializers.IntegerField()
    excluidos = serializers.IntegerField()
    enviados = serializers.IntegerField()
    falhas = serializers.IntegerField()
    ignorados = serializers.IntegerField()
    percentual = serializers.IntegerField()
    motivo_pausa = serializers.CharField()


class VersaoDisparoSerializer(CrmSerializer):
    nome_meta = serializers.CharField()
    corpo = serializers.CharField()


class DistribuicaoSerializer(CrmSerializer):
    data = serializers.DateField()
    quantidade = serializers.IntegerField()


class EstimativaSerializer(CrmSerializer):
    cabem_hoje = serializers.IntegerField()
    distribuicao = DistribuicaoSerializer(many=True)
    sem_previsao = serializers.IntegerField()


class DisparoDetalheSerializer(DisparoItemSerializer):
    versao = VersaoDisparoSerializer()
    confirmado_por = UsuarioMiniSerializer(allow_null=True)
    iniciado_em = serializers.DateTimeField(allow_null=True)
    cancelado_por = UsuarioMiniSerializer(allow_null=True)
    cancelado_em = serializers.DateTimeField(allow_null=True)
    pendentes = serializers.IntegerField()
    motivos_exclusao = MotivoContagemSerializer(many=True)
    motivos_ignorados = MotivoContagemSerializer(many=True)
    custo_estimado = serializers.CharField()
    exemplo = serializers.CharField()
    estimativa = EstimativaSerializer(allow_null=True)
    situacao_envio = serializers.CharField()
    situacao_envio_display = serializers.CharField()


class DestinatarioSerializer(CrmSerializer):
    id = serializers.IntegerField()
    ordem = serializers.IntegerField()
    cliente = ClienteMiniCobrancaSerializer()
    parcela = ParcelaMiniSerializer(allow_null=True)
    situacao = serializers.ChoiceField(choices=ItemDisparo.Situacao.values)
    situacao_display = serializers.CharField()
    motivo = serializers.CharField()
    motivo_display = serializers.CharField()
    telefone = serializers.CharField()
    processado_em = serializers.DateTimeField(allow_null=True)
    conversa_id = serializers.IntegerField(allow_null=True)

