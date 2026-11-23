"""Referências curtas (loja, usuário, produto) usadas nas respostas do módulo de crédito."""
from rest_framework import serializers

from ..regras import nome_usuario

DINHEIRO = {'max_digits': 12, 'decimal_places': 2}


class CreditoLojaRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class CreditoUsuarioRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.SerializerMethodField()

    def get_nome(self, user) -> str:
        return nome_usuario(user)


class CreditoMarcaRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class CreditoProdutoRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    is_iphone = serializers.BooleanField()


class CreditoProdutoDetalheSerializer(CreditoProdutoRefSerializer):
    valor = serializers.DecimalField(allow_null=True, **DINHEIRO)
    entrada_cliente = serializers.DecimalField(**DINHEIRO)
    marca = CreditoMarcaRefSerializer(allow_null=True)


def usuario_da_requisicao(serializer):
    request = serializer.context.get('request')
    return getattr(request, 'user', None)
