"""Serializers de entrada (corpo das requisições) de contas a receber."""
from rest_framework import serializers

from vendas.models import ORIGEM_BAIXA_PAGBANK, ORIGENS_BAIXA, Contato

from .arquivos import validar_comprovante
from .constantes import CHAVES_SITUACAO, DESCONTO_MAXIMO, MAXIMO_PARCELAS_EXTRAS, MINIMO_CARACTERES_MOTIVO
from .servicos import CAMPOS_EDITAVEIS_PARCELA

ORIGENS_BAIXA_MANUAL = [(chave, rotulo) for chave, rotulo in ORIGENS_BAIXA if chave != ORIGEM_BAIXA_PAGBANK]

TAMANHO_MAXIMO_MOTIVO = 1000
TAMANHO_MAXIMO_REFERENCIAS = 5000


def campo_motivo(obrigatorio: bool) -> serializers.CharField:
    if obrigatorio:
        return serializers.CharField(min_length=MINIMO_CARACTERES_MOTIVO, max_length=TAMANHO_MAXIMO_MOTIVO)
    return serializers.CharField(required=False, allow_blank=True, max_length=TAMANHO_MAXIMO_MOTIVO)


class SemCamposDesconhecidosMixin:
    """Recusa campos fora da lista (ex.: `valor` de parcela, que não é editável)."""

    campos_aceitos: tuple = ()

    def validate(self, attrs):
        desconhecidos = sorted(set(getattr(self, 'initial_data', {}) or {}) - set(self.campos_aceitos))
        if desconhecidos:
            raise serializers.ValidationError({campo: ['Campo não editável.'] for campo in desconhecidos})
        return super().validate(attrs)


class SituacaoEntradaSerializer(serializers.Serializer):
    """Uma situação de cobrança ou um status de pagamento; sem `ativo`, alterna."""

    situacao = serializers.ChoiceField(choices=CHAVES_SITUACAO, required=False)
    status_pagamento = serializers.IntegerField(required=False, min_value=1)
    ativo = serializers.BooleanField(required=False, allow_null=True, default=None)
    motivo = campo_motivo(obrigatorio=False)

    def validate(self, attrs):
        informados = [campo for campo in ('situacao', 'status_pagamento') if attrs.get(campo) is not None]
        if len(informados) != 1:
            raise serializers.ValidationError('Informe `situacao` ou `status_pagamento` (apenas um).')
        return attrs


class DescontoEntradaSerializer(SemCamposDesconhecidosMixin, serializers.Serializer):
    campos_aceitos = ('porcentagem_desconto', 'motivo')

    porcentagem_desconto = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=DESCONTO_MAXIMO,
    )
    motivo = campo_motivo(obrigatorio=False)


class ParcelaEdicaoSerializer(SemCamposDesconhecidosMixin, serializers.Serializer):
    campos_aceitos = CAMPOS_EDITAVEIS_PARCELA + ('motivo',)

    valor_pago = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    pago = serializers.BooleanField(required=False)
    data_pagamento = serializers.DateField(required=False, allow_null=True)
    data_vencimento = serializers.DateField(required=False)
    # Baixa manual: Pix do carnê, transferência, dinheiro... ('pagbank' só a baixa automática grava).
    origem_baixa = serializers.ChoiceField(choices=ORIGENS_BAIXA_MANUAL, required=False, allow_blank=True)
    motivo = campo_motivo(obrigatorio=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not any(campo in attrs for campo in CAMPOS_EDITAVEIS_PARCELA):
            raise serializers.ValidationError('Informe ao menos um campo para alterar.')
        return attrs


class NovaParcelaSerializer(serializers.Serializer):
    data_vencimento = serializers.DateField(required=False, allow_null=True, default=None)


class AdicionarParcelasSerializer(serializers.Serializer):
    parcelas = NovaParcelaSerializer(many=True, allow_empty=False)
    motivo = campo_motivo(obrigatorio=False)

    def validate_parcelas(self, parcelas):
        if len(parcelas) > MAXIMO_PARCELAS_EXTRAS:
            raise serializers.ValidationError(
                f'É permitido adicionar no máximo {MAXIMO_PARCELAS_EXTRAS} parcelas extras por vez.'
            )
        return parcelas


class ComprovanteEntradaSerializer(serializers.Serializer):
    arquivo = serializers.FileField(validators=[validar_comprovante])
    observacao = serializers.CharField(required=False, allow_blank=True, max_length=255, default='')


class QuitacaoEntradaSerializer(serializers.Serializer):
    motivo = campo_motivo(obrigatorio=True)


class ContatoEntradaSerializer(serializers.ModelSerializer):
    observacao = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=5000)

    class Meta:
        model = Contato
        fields = ['data', 'observacao']


class BoPdfEntradaSerializer(serializers.Serializer):
    """Referências pessoais editadas na prévia; vazio usa o texto padrão."""

    referencias_personais = serializers.CharField(
        required=False, allow_blank=True, max_length=TAMANHO_MAXIMO_REFERENCIAS, default='',
    )
