"""Formatos de resposta das ações, dos KPIs, da busca e do QR (documentam o OpenAPI)."""
from rest_framework import serializers

from .solicitacao_detalhe import CreditoSolicitacaoDetalheSerializer
from .solicitacao_lista import CreditoBuscaItemSerializer, CreditoSolicitacaoListaSerializer


class CreditoAcaoRespostaSerializer(serializers.Serializer):
    mensagem = serializers.CharField()
    solicitacao = CreditoSolicitacaoListaSerializer()


class CreditoGerarVendaRespostaSerializer(CreditoAcaoRespostaSerializer):
    venda_id = serializers.IntegerField()


class CreditoEdicaoRespostaSerializer(CreditoSolicitacaoDetalheSerializer):
    aviso = serializers.SerializerMethodField(help_text='Aviso de dados já cadastrados em outra solicitação.')

    def get_aviso(self, cliente) -> str | None:
        return self.context.get('aviso')


class CreditoOpcaoSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    rotulo = serializers.CharField()


class CreditoContadoresSerializer(serializers.Serializer):
    por_status = serializers.DictField(child=serializers.IntegerField(), help_text='{"EA": 3, "A": 10, "R": 2, "C": 1}')
    total = serializers.IntegerField()
    aprovadas_sem_venda = serializers.IntegerField()


class CreditoKpisSerializer(CreditoContadoresSerializer):
    online = CreditoContadoresSerializer(help_text='Os mesmos contadores, só das análises online.')
    analise_rapida = CreditoContadoresSerializer(help_text='Os mesmos contadores, só das que vieram de uma análise rápida.')
    status_opcoes = CreditoOpcaoSerializer(many=True)
    status_app_opcoes = CreditoOpcaoSerializer(many=True)


class CreditoBuscaRespostaSerializer(serializers.Serializer):
    resultados = CreditoBuscaItemSerializer(many=True)


class CreditoQrInstalacaoSerializer(serializers.Serializer):
    qr_instalacao = serializers.CharField(help_text='Imagem PNG em data URI (QR de instalação do cliente).')
    codigo_instalacao = serializers.CharField()
    qr_aplicativo = serializers.CharField(allow_null=True, help_text='QR do app da loja CredFacil (data URI).')
    codigo_aplicativo = serializers.CharField(allow_null=True)


class CreditoLogSerasaRespostaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tipo = serializers.CharField()
    aberto_em = serializers.DateTimeField()


class CreditoProdutoOpcaoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField(help_text='Rótulo do form (nome, marca e entrada).')
    marca_id = serializers.IntegerField(allow_null=True)
    is_iphone = serializers.BooleanField()
    valor = serializers.CharField(allow_null=True)
    entrada_cliente = serializers.CharField(allow_null=True)


class CreditoAutenticadorOpcaoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    numero = serializers.CharField()
    descricao = serializers.CharField(allow_null=True)


class CreditoOpcoesEdicaoSerializer(serializers.Serializer):
    produtos = CreditoProdutoOpcaoSerializer(many=True)
    parcelas_por_marca = serializers.DictField(
        child=serializers.ListField(child=serializers.IntegerField()), help_text='{"<marca_id>": [10, 12]}',
    )
    data_pagamento = CreditoOpcaoSerializer(many=True)
    numeros_autenticadores = CreditoAutenticadorOpcaoSerializer(many=True, allow_null=True)
