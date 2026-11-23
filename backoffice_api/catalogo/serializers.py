"""Serializers do catálogo (campos explícitos; nada dos campos legados de produto)."""
import re
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from produtos.models import Marca, Parcelamento, Produto, TipoProduto
from vendas.models import Loja

from .servicos import simulacao_do_detalhe

PERMISSAO_ALTERAR_ASSISTENCIA = 'assistencia.view_assistencia'
MAXIMO_PARCELAS = 120
TAMANHO_MAXIMO_MOTIVO = 1000
PADRAO_COR = re.compile(r'^(#[0-9A-Fa-f]{3,8}|[a-z][a-z0-9-]{0,19})$')
ZERO = Decimal('0')


def _nome_usuario(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.username


class CatalogoLojaResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loja
        fields = ['id', 'nome']


class CatalogoMarcaResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Marca
        fields = ['id', 'nome', 'cor', 'icone']


class CatalogoTipoResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoProduto
        fields = ['id', 'nome']


class CatalogoMotivoOpcionalSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=TAMANHO_MAXIMO_MOTIVO)


# --- simulação --------------------------------------------------------------------------------

class CatalogoOpcaoSimulacaoSerializer(serializers.Serializer):
    qtd_vezes = serializers.IntegerField()
    porcentagem_juros = serializers.DecimalField(max_digits=5, decimal_places=2)
    porcentagem_desconto = serializers.DecimalField(max_digits=5, decimal_places=2)
    valor_financiado = serializers.DecimalField(max_digits=14, decimal_places=2)
    valor_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    valor_parcela = serializers.DecimalField(max_digits=14, decimal_places=2)


class CatalogoSimulacaoSerializer(serializers.Serializer):
    valor = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    entrada = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    opcoes = CatalogoOpcaoSimulacaoSerializer(many=True)
    aviso = serializers.CharField(allow_null=True)


class CatalogoSimulacaoEntradaSerializer(serializers.Serializer):
    entrada = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, required=False)


# --- produtos ---------------------------------------------------------------------------------

class CatalogoProdutoListaSerializer(serializers.ModelSerializer):
    marca = CatalogoMarcaResumoSerializer(read_only=True)
    tipo = CatalogoTipoResumoSerializer(read_only=True)

    class Meta:
        model = Produto
        fields = ['id', 'codigo', 'nome', 'valor', 'entrada_cliente', 'marca', 'tipo', 'is_iphone', 'ativo']


class CatalogoProdutoDetalheSerializer(CatalogoProdutoListaSerializer):
    criado_por = serializers.SerializerMethodField()
    modificado_por = serializers.SerializerMethodField()
    simulacao = serializers.SerializerMethodField()

    class Meta(CatalogoProdutoListaSerializer.Meta):
        fields = CatalogoProdutoListaSerializer.Meta.fields + [
            'criado_em', 'modificado_em', 'criado_por', 'modificado_por', 'simulacao',
        ]

    def get_criado_por(self, obj) -> str | None:
        return _nome_usuario(obj.criado_por)

    def get_modificado_por(self, obj) -> str | None:
        return _nome_usuario(obj.modificado_por)

    @extend_schema_field(CatalogoSimulacaoSerializer)
    def get_simulacao(self, obj) -> dict:
        return CatalogoSimulacaoSerializer(simulacao_do_detalhe(obj)).data


class CatalogoProdutoEntradaSerializer(serializers.ModelSerializer):
    """Criação/edição. `marca` só entre as marcas visíveis (contexto `marcas`)."""

    valor = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=ZERO, allow_null=True, required=False
    )
    entrada_cliente = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=ZERO, required=False)
    tipo = serializers.PrimaryKeyRelatedField(queryset=TipoProduto.objects.all(), allow_null=True, required=False)
    marca = serializers.PrimaryKeyRelatedField(
        queryset=Marca.objects.none(), allow_null=True, required=False,
        error_messages={'does_not_exist': 'Marca não encontrada ou indisponível para a sua loja.'},
    )

    class Meta:
        model = Produto
        fields = ['nome', 'valor', 'entrada_cliente', 'tipo', 'marca', 'is_iphone']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        marcas = self.context.get('marcas')
        if marcas is not None:
            self.fields['marca'].queryset = marcas

    def validate(self, attrs: dict) -> dict:
        instancia = self.instance
        valor = attrs['valor'] if 'valor' in attrs else getattr(instancia, 'valor', None)
        entrada = attrs.get('entrada_cliente', getattr(instancia, 'entrada_cliente', ZERO))
        if valor is not None and entrada is not None and entrada > valor:
            raise serializers.ValidationError(
                {'entrada_cliente': ['A entrada mínima não pode ser maior que o valor base.']}
            )
        return attrs


# --- tipos de produto -------------------------------------------------------------------------

class CatalogoTipoProdutoSerializer(serializers.ModelSerializer):
    """Leitura e escrita; `assistencia` só muda com `assistencia.view_assistencia` (como a tela)."""

    class Meta:
        model = TipoProduto
        fields = ['id', 'nome', 'numero_serial', 'assistencia']
        read_only_fields = ['id']

    def validate_assistencia(self, valor: bool) -> bool:
        user = self.context['request'].user
        atual = self.instance.assistencia if self.instance else False
        if valor != atual and not user.has_perm(PERMISSAO_ALTERAR_ASSISTENCIA):
            raise serializers.ValidationError('Você não tem permissão para alterar este campo.')
        return valor


# --- marcas -----------------------------------------------------------------------------------

class CatalogoMarcaSerializer(serializers.ModelSerializer):
    """Leitura. `lojas_permitidas` mostra só as lojas do escopo de quem consulta (prefetch)."""

    icone_nome = serializers.CharField(source='get_icone_display', read_only=True)
    lojas_permitidas = CatalogoLojaResumoSerializer(many=True, read_only=True)
    total_produtos = serializers.IntegerField(read_only=True)
    total_parcelamentos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Marca
        fields = [
            'id', 'nome', 'cor', 'icone', 'icone_nome', 'ativo', 'lojas_permitidas',
            'total_produtos', 'total_parcelamentos',
        ]


class CatalogoMarcaEntradaSerializer(serializers.ModelSerializer):
    """Criação/edição. Situação muda só por ativar/desativar."""

    cor = serializers.CharField(max_length=20, required=False)
    lojas_permitidas = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Loja.objects.all(), required=False,
        error_messages={'does_not_exist': 'Loja não encontrada.'},
    )

    class Meta:
        model = Marca
        fields = ['nome', 'cor', 'icone', 'lojas_permitidas']

    def validate_cor(self, valor: str) -> str:
        valor = valor.strip()
        if not PADRAO_COR.match(valor):
            raise serializers.ValidationError('Use uma cor hexadecimal (ex.: #ff0000) ou um nome de cor.')
        return valor

    def validate_lojas_permitidas(self, lojas: list) -> list:
        escopo = self.context.get('escopo_escrita')
        if escopo is None:
            return lojas
        atuais = set(self.instance.lojas_permitidas.values_list('pk', flat=True)) if self.instance else set()
        fora = sorted(loja.nome for loja in lojas if loja.pk not in escopo and loja.pk not in atuais)
        if fora:
            raise serializers.ValidationError(f'Lojas fora do seu escopo: {", ".join(fora)}.')
        return lojas


class CatalogoIconeMarcaSerializer(serializers.Serializer):
    valor = serializers.CharField()
    rotulo = serializers.CharField()


# --- parcelamentos ----------------------------------------------------------------------------

class CatalogoParcelamentoSerializer(serializers.ModelSerializer):
    marca = CatalogoMarcaResumoSerializer(read_only=True)

    class Meta:
        model = Parcelamento
        fields = ['id', 'marca', 'qtd_vezes', 'porcentagem_juros', 'porcentagem_desconto']


class CatalogoParcelamentoEntradaSerializer(serializers.ModelSerializer):
    """Criação/edição; (marca, qtd_vezes) única, conferida aqui com mensagem clara."""

    marca = serializers.PrimaryKeyRelatedField(
        queryset=Marca.objects.none(), allow_null=True, required=False,
        error_messages={'does_not_exist': 'Marca não encontrada ou indisponível para a sua loja.'},
    )
    qtd_vezes = serializers.IntegerField(min_value=1, max_value=MAXIMO_PARCELAS)
    porcentagem_juros = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=ZERO)
    porcentagem_desconto = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=ZERO, max_value=Decimal('100'), required=False
    )

    class Meta:
        model = Parcelamento
        fields = ['marca', 'qtd_vezes', 'porcentagem_juros', 'porcentagem_desconto']
        validators: list = []  # a unicidade é conferida em `validate`, com mensagem própria

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        marcas = self.context.get('marcas')
        if marcas is not None:
            self.fields['marca'].queryset = marcas

    def validate(self, attrs: dict) -> dict:
        instancia = self.instance
        marca = attrs['marca'] if 'marca' in attrs else getattr(instancia, 'marca', None)
        qtd_vezes = attrs.get('qtd_vezes', getattr(instancia, 'qtd_vezes', None))
        repetidos = Parcelamento.objects.filter(marca=marca, qtd_vezes=qtd_vezes)
        if instancia is not None:
            repetidos = repetidos.exclude(pk=instancia.pk)
        if repetidos.exists():
            nome_marca = marca.nome if marca else 'sem marca'
            mensagem = f'Já existe um parcelamento de {qtd_vezes}x cadastrado para a marca {nome_marca}.'
            raise serializers.ValidationError({'qtd_vezes': [mensagem], 'non_field_errors': [mensagem]})
        return attrs
