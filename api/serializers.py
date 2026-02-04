from rest_framework import serializers

from financeiro.models import Repasse
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ContatoAdicional,
    InformacaoPessoal,
    ComprovantesCliente,
    Loja,
    Venda,
)
from produtos.models import Produto
from vendas.models import ProdutoVenda, Pagamento


class LojaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loja
        fields = "__all__"

    def validate(self, attrs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and not (user.is_superuser or user.groups.filter(name="ADMINISTRADOR").exists()):
            attrs.pop("pode_vender_iphone", None)
        return attrs

    def update(self, instance, validated_data):
        if "credfacil" not in self.initial_data:
            validated_data["credfacil"] = instance.credfacil
        return super().update(instance, validated_data)


class LojaListSerializer(LojaSerializer):
    repasses_info = serializers.SerializerMethodField()

    class Meta(LojaSerializer.Meta):
        fields = "__all__"

    def get_repasses_info(self, obj):
        repasses, atrasados = obj.get_repasses_status()
        return {"repasses": repasses, "atrasados": atrasados}


class RepasseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Repasse
        fields = ["id", "valor", "data", "status", "observacao", "criado_por", "criado_em"]


class VendaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome", read_only=True)

    class Meta:
        model = Venda
        fields = ["id", "data_venda", "cliente", "cliente_nome", "repasse_logista", "is_deleted"]


class ContatoAdicionalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContatoAdicional
        fields = ["id", "nome_adicional", "contato", "endereco_adicional", "obteve_contato"]


class InformacaoPessoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = InformacaoPessoal
        fields = ["id", "nome", "contato", "endereco", "obteve_contato"]


class ComprovantesClienteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComprovantesCliente
        fields = [
            "id",
            "documento_identificacao_frente",
            "documento_identificacao_frente_analise",
            "documento_identificacao_verso",
            "documento_identificacao_verso_analise",
            "comprovante_residencia",
            "comprovante_residencia_analise",
            "consulta_serasa",
            "consulta_serasa_analise",
            "restricao",
            "foto_cliente",
        ]


class AnaliseCreditoClienteSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    status_app_display = serializers.CharField(source="get_status_aplicativo_display", read_only=True)
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)
    produto_is_iphone = serializers.BooleanField(source="produto.is_iphone", read_only=True)
    imei_value = serializers.CharField(source="imei.imei", read_only=True)
    venda_gerada = serializers.SerializerMethodField()

    class Meta:
        model = AnaliseCreditoCliente
        fields = [
            "id",
            "cliente",
            "loja",
            "data_analise",
            "data_aprovacao",
            "data_reprovacao",
            "data_cancelamento",
            "aprovado_por",
            "status",
            "status_display",
            "status_aplicativo",
            "status_app_display",
            "analise_online",
            "data_pagamento",
            "numero_parcelas",
            "produto",
            "produto_nome",
            "produto_is_iphone",
            "imei",
            "imei_value",
            "imei_informado",
            "venda",
            "observacao",
            "email_icloud",
            "senha_icloud",
            "icloud_configurado_vendedor",
            "icloud_confirmado_analista",
            "venda_gerada",
        ]

    def get_venda_gerada(self, obj):
        return bool(obj.venda_id)


class ClienteSolicitacaoSerializer(serializers.ModelSerializer):
    loja_nome = serializers.CharField(source="loja.nome", read_only=True)
    contato_adicional = ContatoAdicionalSerializer(read_only=True)
    informacao_pessoal = InformacaoPessoalSerializer(read_only=True)
    comprovantes = ComprovantesClienteSerializer(read_only=True)
    analise_credito = AnaliseCreditoClienteSerializer(read_only=True)

    class Meta:
        model = Cliente
        fields = [
            "id",
            "loja",
            "loja_nome",
            "nome",
            "email",
            "telefone",
            "cpf",
            "nascimento",
            "rg",
            "cep",
            "endereco",
            "bairro",
            "cidade",
            "profissao",
            "quantidade_dependentes",
            "recebe_auxilio",
            "total_renda",
            "observacao_cliente",
            "contato_adicional",
            "informacao_pessoal",
            "comprovantes",
            "analise_credito",
        ]


class ProdutoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Produto
        fields = "__all__"


class ProdutoVendaSerializer(serializers.ModelSerializer):
    produto_nome = serializers.CharField(source="produto.nome", read_only=True)

    class Meta:
        model = ProdutoVenda
        fields = [
            "id",
            "produto",
            "produto_nome",
            "imei",
            "valor_unitario",
            "quantidade",
            "valor_desconto",
        ]


class PagamentoSerializer(serializers.ModelSerializer):
    tipo_nome = serializers.CharField(source="tipo_pagamento.nome", read_only=True)

    class Meta:
        model = Pagamento
        fields = [
            "id",
            "tipo_pagamento",
            "tipo_nome",
            "valor",
            "parcelas",
            "data_primeira_parcela",
            "porcentagem_desconto",
            "bloqueado",
            "desativado",
            "devolucao",
            "quitado",
        ]


class VendaSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome", read_only=True)
    itens_venda = ProdutoVendaSerializer(many=True, read_only=True)
    pagamentos = PagamentoSerializer(many=True, read_only=True)

    class Meta:
        model = Venda
        fields = [
            "id",
            "loja",
            "cliente",
            "cliente_nome",
            "vendedor",
            "data_venda",
            "observacao",
            "repasse_logista",
            "documento_assinado",
            "foto_cliente",
            "imagem_imei",
            "is_deleted",
            "is_trocado",
            "itens_venda",
            "pagamentos",
        ]
