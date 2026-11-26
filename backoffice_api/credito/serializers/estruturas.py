"""Formato das estruturas montadas pelos serviços do módulo (documentam o OpenAPI)."""
from rest_framework import serializers

from .comum import DINHEIRO, CreditoUsuarioRefSerializer


class CreditoArquivoSerializer(serializers.Serializer):
    campo = serializers.CharField()
    rotulo = serializers.CharField()
    presente = serializers.BooleanField()
    url = serializers.CharField(allow_null=True, help_text='Endpoint da API que entrega o arquivo.')
    analisado = serializers.BooleanField(allow_null=True)
    serasa = serializers.BooleanField()


class CreditoComprovantesSerializer(serializers.Serializer):
    arquivos = CreditoArquivoSerializer(many=True)
    restricao = serializers.BooleanField(allow_null=True, help_text='Só para quem vê a consulta Serasa.')


class CreditoOpcaoParcelamentoSerializer(serializers.Serializer):
    qtd_vezes = serializers.IntegerField()
    porcentagem_juros = serializers.DecimalField(**DINHEIRO)
    porcentagem_desconto = serializers.DecimalField(**DINHEIRO)
    entrada = serializers.DecimalField(**DINHEIRO)
    valor_financiado = serializers.DecimalField(**DINHEIRO)
    valor_total = serializers.DecimalField(**DINHEIRO)
    valor_parcela = serializers.DecimalField(**DINHEIRO)
    repasse_logista = serializers.DecimalField(**DINHEIRO)
    selecionada = serializers.BooleanField()


class CreditoSimulacaoSerializer(serializers.Serializer):
    valor_produto = serializers.DecimalField(allow_null=True, **DINHEIRO)
    entrada_minima = serializers.DecimalField(allow_null=True, **DINHEIRO)
    numero_parcelas = serializers.IntegerField(allow_null=True)
    opcoes = CreditoOpcaoParcelamentoSerializer(many=True)
    selecionada = CreditoOpcaoParcelamentoSerializer(allow_null=True)
    erro = serializers.CharField(allow_null=True)


class CreditoMudancaSerializer(serializers.Serializer):
    campo = serializers.CharField()
    rotulo = serializers.CharField()
    de = serializers.CharField(allow_null=True)
    para = serializers.CharField(allow_null=True)


class CreditoEventoSerializer(serializers.Serializer):
    tipo = serializers.ChoiceField(choices=['criacao', 'alteracao', 'observacao'])
    origem = serializers.ChoiceField(choices=['analise', 'cliente', 'comprovantes', 'observacao'])
    data = serializers.DateTimeField()
    usuario = CreditoUsuarioRefSerializer(allow_null=True)
    titulo = serializers.CharField()
    mudancas = CreditoMudancaSerializer(many=True)
    texto = serializers.CharField(allow_null=True)


class CreditoAcoesSerializer(serializers.Serializer):
    editar = serializers.BooleanField()
    aprovar = serializers.BooleanField()
    reprovar = serializers.BooleanField()
    cancelar = serializers.BooleanField()
    observar = serializers.BooleanField()
    alterar_status_app = serializers.BooleanField()
    instalar_app = serializers.BooleanField()
    confirmar_instalacao = serializers.BooleanField()
    confirmar_icloud = serializers.BooleanField()
    informar_imei = serializers.BooleanField()
    gerar_venda = serializers.BooleanField()
    notificar_vendedor = serializers.BooleanField(help_text='Venda liberada: pode reenviar o aviso ao vendedor.')
    ver_serasa = serializers.BooleanField()


class CreditoEdicaoSerializer(serializers.Serializer):
    pode_editar = serializers.BooleanField()
    campos_editaveis = serializers.ListField(child=serializers.CharField())


class CreditoVendaRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    data_venda = serializers.DateTimeField()
    cancelada = serializers.BooleanField(source='is_deleted')
    trocada = serializers.BooleanField(source='is_trocado')
    vendedor = CreditoUsuarioRefSerializer(allow_null=True)


class CreditoImeiRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    imei = serializers.CharField()


class CreditoNumeroAutenticadorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    numero = serializers.CharField()
    descricao = serializers.CharField(allow_null=True)


class CreditoIcloudSerializer(serializers.Serializer):
    email = serializers.CharField(allow_null=True)
    configurado_vendedor = serializers.BooleanField()
    confirmado_analista = serializers.BooleanField()


class CreditoObservacaoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    texto = serializers.CharField()
    autor = CreditoUsuarioRefSerializer(allow_null=True)
    criado_em = serializers.DateTimeField()
