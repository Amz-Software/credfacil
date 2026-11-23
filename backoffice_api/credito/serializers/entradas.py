"""Corpos de entrada das ações do módulo de crédito."""
from rest_framework import serializers

from vendas.models import AnaliseCreditoCliente

MOTIVO_MINIMO = 5
TEXTO_MAXIMO = 5000


class CreditoMotivoSerializer(serializers.Serializer):
    motivo = serializers.CharField(
        min_length=MOTIVO_MINIMO,
        max_length=TEXTO_MAXIMO,
        error_messages={
            'required': 'Informe o motivo.',
            'blank': 'Informe o motivo.',
            'null': 'Informe o motivo.',
            'min_length': f'O motivo deve ter pelo menos {MOTIVO_MINIMO} caracteres.',
            'max_length': f'O motivo pode ter no máximo {TEXTO_MAXIMO} caracteres.',
        },
    )


class CreditoObservacaoEntradaSerializer(serializers.Serializer):
    texto = serializers.CharField(
        max_length=TEXTO_MAXIMO,
        error_messages={
            'required': 'A observação não pode estar vazia.',
            'blank': 'A observação não pode estar vazia.',
            'null': 'A observação não pode estar vazia.',
            'max_length': f'A observação pode ter no máximo {TEXTO_MAXIMO} caracteres.',
        },
    )


class CreditoStatusAppEntradaSerializer(serializers.Serializer):
    status_app = serializers.ChoiceField(
        choices=AnaliseCreditoCliente.STATUS_APP_CHOICES,
        error_messages={'required': 'Informe o status do aplicativo.', 'invalid_choice': 'Status inválido.'},
    )


class CreditoImeiEntradaSerializer(serializers.Serializer):
    imei = serializers.CharField(
        max_length=20,
        error_messages={
            'required': 'IMEI é obrigatório.',
            'blank': 'IMEI é obrigatório.',
            'max_length': 'O IMEI pode ter no máximo 20 caracteres.',
        },
    )


class CreditoLogSerasaEntradaSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(
        choices=[('serasa', 'Consulta Serasa'), ('serasa_2', 'Consulta Serasa 2')],
        error_messages={'required': "Informe o tipo ('serasa' ou 'serasa_2').", 'invalid_choice': 'Tipo inválido.'},
    )


class CreditoUploadEntradaSerializer(serializers.Serializer):
    arquivo = serializers.FileField(
        error_messages={'required': 'Selecione o arquivo.', 'empty': 'O arquivo está vazio.'},
        help_text='PDF, JPG, PNG ou WEBP, até 10 MB.',
    )


class CreditoMensagemSerializer(serializers.Serializer):
    mensagem = serializers.CharField()
