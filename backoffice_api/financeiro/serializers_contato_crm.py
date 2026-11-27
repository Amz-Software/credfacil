"""Saída do painel de contato de cobrança (aba Contatos do detalhe da conta)."""
from rest_framework import serializers


class OpcaoSerializer(serializers.Serializer):
    valor = serializers.CharField()
    rotulo = serializers.CharField()


class OpcoesContatoSerializer(serializers.Serializer):
    canais = OpcaoSerializer(many=True)
    resultados_cliente = OpcaoSerializer(many=True)
    resultados_referencia = OpcaoSerializer(many=True)


class StatusContatoSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    rotulo = serializers.CharField()


class TelefoneCrmSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    numero = serializers.CharField()
    origem = serializers.CharField()
    situacao = serializers.CharField()
    situacao_rotulo = serializers.CharField()
    situacao_estado = serializers.CharField()
    eh_referencia = serializers.BooleanField()
    nome_contato = serializers.CharField(allow_blank=True)
    observacao = serializers.CharField(allow_blank=True)
    utilizavel = serializers.BooleanField()


class ItemLinhaDoTempoSerializer(serializers.Serializer):
    id = serializers.CharField()
    origem = serializers.ChoiceField(choices=['manual', 'tentativa', 'nota'])
    quando = serializers.DateTimeField()
    somente_data = serializers.BooleanField(help_text='Registro manual: só a data vale.')
    titulo = serializers.CharField()
    texto = serializers.CharField(allow_blank=True)
    autor = serializers.CharField(allow_null=True)
    contato_id = serializers.IntegerField(allow_null=True, help_text='Registro manual editável.')
    automatica = serializers.BooleanField(help_text='Aviso enviado pela régua de cobrança.')
    canal = serializers.CharField(allow_null=True)
    numero = serializers.CharField(allow_null=True)
    resultado = serializers.CharField(allow_null=True)
    resultado_estado = serializers.CharField(allow_null=True)
    parcela = serializers.IntegerField(allow_null=True)


class PainelContatoSerializer(serializers.Serializer):
    crm_disponivel = serializers.BooleanField()
    status = StatusContatoSerializer(allow_null=True)
    alerta = serializers.BooleanField(help_text='Parcela vencida, recebeu aviso e não respondeu.')
    telefones = TelefoneCrmSerializer(many=True)
    conversa_id = serializers.IntegerField(allow_null=True)
    pode_anotar = serializers.BooleanField()
    linha_do_tempo = ItemLinhaDoTempoSerializer(many=True)
    opcoes = OpcoesContatoSerializer()
