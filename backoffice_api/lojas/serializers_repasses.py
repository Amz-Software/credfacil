"""Serializers de repasses ao logista e de números autenticadores."""
from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from financeiro.models import Repasse
from vendas.models import Loja, NumeroAutenticador

from .serializers import nome_usuario
from .servicos import ROTULOS_STATUS_REPASSE, STATUS_CRIACAO, STATUS_REPASSE

DINHEIRO = {'max_digits': 10, 'decimal_places': 2}
MINIMO_DIGITOS_TELEFONE = 10
MAXIMO_DIGITOS_TELEFONE = 11


class LojaRefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class RepasseSerializer(serializers.ModelSerializer):
    loja = LojaRefSerializer()
    data = serializers.SerializerMethodField()
    status_rotulo = serializers.SerializerMethodField()
    criado_por = serializers.SerializerMethodField()
    atualizado_por = serializers.SerializerMethodField()

    class Meta:
        model = Repasse
        fields = ['id', 'loja', 'valor', 'data', 'status', 'status_rotulo', 'observacao',
                  'criado_por', 'criado_em', 'atualizado_por', 'atualizado_em']

    @extend_schema_field(serializers.DateField())
    def get_data(self, repasse) -> str:
        return timezone.localtime(repasse.data).date().isoformat()

    def get_status_rotulo(self, repasse) -> str:
        return ROTULOS_STATUS_REPASSE.get(repasse.status, repasse.status)

    def get_criado_por(self, repasse) -> str | None:
        return nome_usuario(repasse.criado_por) if repasse.criado_por_id else None

    def get_atualizado_por(self, repasse) -> str | None:
        return nome_usuario(repasse.atualizado_por) if repasse.atualizado_por_id else None


class RepasseCriacaoSerializer(serializers.Serializer):
    """`loja` é validada contra o escopo do usuário (queryset vindo do contexto)."""

    loja = serializers.PrimaryKeyRelatedField(queryset=Loja.objects.none())
    valor = serializers.DecimalField(min_value=Decimal('0.01'), **DINHEIRO)
    data = serializers.DateField()
    status = serializers.ChoiceField(choices=STATUS_CRIACAO, default='pendente')
    observacao = serializers.CharField(required=False, allow_blank=True, default='', max_length=5000)

    def __init__(self, *args, lojas=None, **kwargs):
        super().__init__(*args, **kwargs)
        if lojas is not None:
            self.fields['loja'].queryset = lojas


class PeriodoDaLojaSerializer(serializers.Serializer):
    """Identifica um período do calendário: loja + data do repasse (dia 6, 16 ou 26)."""

    loja = serializers.IntegerField(min_value=1)
    data = serializers.DateField()


class RepasseEdicaoSerializer(serializers.Serializer):
    valor = serializers.DecimalField(min_value=Decimal('0.01'), required=False, **DINHEIRO)
    data = serializers.DateField(required=False)
    status = serializers.ChoiceField(choices=STATUS_REPASSE, required=False)
    observacao = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate(self, attrs):
        desconhecidos = sorted(set(getattr(self, 'initial_data', {}) or {}) - set(self.fields))
        if desconhecidos:
            raise serializers.ValidationError({campo: ['Campo não editável.'] for campo in desconhecidos})
        if not ({'valor', 'data', 'status', 'observacao'} & set(attrs)):
            raise serializers.ValidationError('Informe ao menos um campo para alterar.')
        return attrs


class PeriodoRepasseSerializer(serializers.Serializer):
    data = serializers.DateField()
    inicio_periodo = serializers.DateField()
    fim_periodo = serializers.DateField()
    qtd_vendas = serializers.IntegerField()
    valor_total_repasse = serializers.DecimalField(max_digits=14, decimal_places=2)
    feito = serializers.BooleanField()
    parcial = serializers.BooleanField()
    atrasado = serializers.BooleanField()


class AgendaDaLojaSerializer(serializers.Serializer):
    loja = LojaRefSerializer()
    atrasados = PeriodoRepasseSerializer(many=True)
    proximos = PeriodoRepasseSerializer(many=True)
    total_atrasados = serializers.IntegerField()


class NumeroAutenticadorSerializer(serializers.ModelSerializer):
    loja = LojaRefSerializer(read_only=True, allow_null=True)
    loja_id = serializers.PrimaryKeyRelatedField(
        source='loja', queryset=Loja.objects.none(), required=False, allow_null=True, write_only=True,
    )

    class Meta:
        model = NumeroAutenticador
        fields = ['id', 'numero', 'descricao', 'ativo', 'loja', 'loja_id', 'criado_em', 'modificado_em']
        read_only_fields = ['criado_em', 'modificado_em']

    def __init__(self, *args, lojas=None, **kwargs):
        super().__init__(*args, **kwargs)
        if lojas is not None:
            self.fields['loja_id'].queryset = lojas

    def validate_numero(self, numero: str) -> str:
        """Mesma regra de `NumeroAutenticadorForm`: 10 ou 11 dígitos, guarda como digitado."""
        digitos = ''.join(filter(str.isdigit, numero or ''))
        if not MINIMO_DIGITOS_TELEFONE <= len(digitos) <= MAXIMO_DIGITOS_TELEFONE:
            raise serializers.ValidationError('Informe um número de telefone válido com DDD (10 ou 11 dígitos).')
        return numero
