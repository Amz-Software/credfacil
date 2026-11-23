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


class CreditoKpisSerializer(serializers.Serializer):
    por_status = serializers.DictField(child=serializers.IntegerField(), help_text='{"EA": 3, "A": 10, "R": 2, "C": 1}')
    total = serializers.IntegerField()
    aprovadas_sem_venda = serializers.IntegerField()
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
