"""Serializers de entrada das ações de venda e validação com erros por campo ("itens.0.imei")."""
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from api.serializers import VendaDocumentosSerializer, VendaTrocaProdutoSerializer
from vendas.forms import PagamentoEdicaoEspecialForm

from .servicos_documentos import validar_arquivo

MOTIVO_MINIMO = 5
MOTIVO_MAXIMO = 1000
PARCELAS_MAXIMAS = 60
DECIMAL = {'max_digits': 10, 'decimal_places': 2}


def achatar_erros(erros, prefixo: str = '') -> dict[str, list[str]]:
    """Converte erros aninhados do DRF em `{"itens.0.imei": ["..."]}` para o contrato de erro."""
    if isinstance(erros, dict):
        campos: dict[str, list[str]] = {}
        for chave, valor in erros.items():
            if chave == 'non_field_errors' and prefixo:
                chave_final = prefixo
            else:
                chave_final = f'{prefixo}.{chave}' if prefixo else str(chave)
            campos.update(achatar_erros(valor, chave_final))
        return campos
    if isinstance(erros, list):
        if all(not isinstance(item, (dict, list)) for item in erros):
            return {prefixo or 'non_field_errors': [str(item) for item in erros]} if erros else {}
        campos = {}
        for indice, item in enumerate(erros):
            campos.update(achatar_erros(item, f'{prefixo}.{indice}' if prefixo else str(indice)))
        return campos
    return {prefixo or 'non_field_errors': [str(erros)]}


def validar_entrada(serializer_class, dados, contexto: dict | None = None) -> dict:
    entrada = serializer_class(data=dados, context=contexto or {})
    if not entrada.is_valid():
        raise ValidationError(achatar_erros(entrada.errors))
    return entrada.validated_data


class MotivoField(serializers.CharField):
    """Motivo obrigatório das decisões sensíveis (vai para a auditoria)."""

    def __init__(self, **kwargs):
        kwargs.setdefault('min_length', MOTIVO_MINIMO)
        kwargs.setdefault('max_length', MOTIVO_MAXIMO)
        kwargs.setdefault('error_messages', {
            'required': 'Informe o motivo.',
            'blank': 'Informe o motivo.',
            'null': 'Informe o motivo.',
            'min_length': f'Descreva o motivo com pelo menos {MOTIVO_MINIMO} caracteres.',
        })
        super().__init__(**kwargs)


class MotivoVendaSerializer(serializers.Serializer):
    motivo = MotivoField()


def _ids_repetidos(linhas: list[dict], campo: str) -> None:
    ids = [linha['id'] for linha in linhas if linha.get('id') is not None]
    if len(ids) != len(set(ids)):
        raise serializers.ValidationError({campo: ['O mesmo registro foi enviado mais de uma vez.']})


# --- edição ------------------------------------------------------------------------

class ItemEdicaoVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    produto = serializers.IntegerField(required=False)
    imei = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=100)
    quantidade = serializers.IntegerField(required=False, min_value=1)
    valor_unitario = serializers.DecimalField(required=False, min_value=0, **DECIMAL)
    valor_desconto = serializers.DecimalField(required=False, min_value=0, **DECIMAL)
    remover = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs.get('id') is None:
            if attrs.get('remover'):
                raise serializers.ValidationError({'remover': ['Só é possível remover um item existente.']})
            faltando = [c for c in ('produto', 'quantidade', 'valor_unitario') if attrs.get(c) is None]
            if faltando:
                raise serializers.ValidationError({c: ['Obrigatório para incluir um item.'] for c in faltando})
        return attrs


class PagamentoEdicaoVendaSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    tipo_pagamento = serializers.IntegerField(required=False)
    valor = serializers.DecimalField(required=False, min_value=0, **DECIMAL)
    parcelas = serializers.IntegerField(required=False, min_value=1, max_value=PARCELAS_MAXIMAS)
    data_primeira_parcela = serializers.DateField(required=False)
    porcentagem_desconto = serializers.DecimalField(
        required=False, min_value=0, max_value=100, max_digits=5, decimal_places=2,
    )
    remover = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs.get('id') is None:
            if attrs.get('remover'):
                raise serializers.ValidationError({'remover': ['Só é possível remover um pagamento existente.']})
            obrigatorios = ('tipo_pagamento', 'valor', 'parcelas', 'data_primeira_parcela')
            faltando = [c for c in obrigatorios if attrs.get(c) is None]
            if faltando:
                raise serializers.ValidationError({c: ['Obrigatório para incluir um pagamento.'] for c in faltando})
        return attrs


class EdicaoVendaSerializer(serializers.Serializer):
    cliente = serializers.IntegerField(required=False)
    vendedor = serializers.IntegerField(required=False)
    observacao = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    itens = ItemEdicaoVendaSerializer(many=True, required=False)
    pagamentos = PagamentoEdicaoVendaSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError('Envie ao menos um campo para alterar.')
        _ids_repetidos(attrs.get('itens') or [], 'itens')
        _ids_repetidos(attrs.get('pagamentos') or [], 'pagamentos')
        return attrs


# --- edição especial -------------------------------------------------------------

class ItemEdicaoEspecialSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    produto = serializers.IntegerField(required=False)
    imei = serializers.CharField(required=False, allow_blank=True, max_length=100)


class PagamentoEdicaoEspecialSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    parcelas = serializers.ChoiceField(choices=[valor for valor, _ in PagamentoEdicaoEspecialForm.PARCELAS_CHOICES])


class EdicaoEspecialVendaSerializer(serializers.Serializer):
    motivo = MotivoField()
    itens = ItemEdicaoEspecialSerializer(many=True, required=False)
    pagamentos = PagamentoEdicaoEspecialSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs.get('itens') and not attrs.get('pagamentos'):
            raise serializers.ValidationError('Envie itens ou pagamentos para alterar.')
        _ids_repetidos(attrs.get('itens') or [], 'itens')
        _ids_repetidos(attrs.get('pagamentos') or [], 'pagamentos')
        return attrs


# --- troca, cancelamento, documentos e autorização ----------------------------------

class TrocaProdutoVendaSerializer(VendaTrocaProdutoSerializer):
    """`produto_atual` = id do item da venda; `imei` = id do EstoqueImei; motivo obrigatório."""

    motivo = MotivoField()


class DocumentosVendaSerializer(VendaDocumentosSerializer):
    """Upload parcial: qualquer subconjunto dos três arquivos, validados pelo conteúdo."""

    def _validar(self, campo, arquivo):
        validar_arquivo(campo, arquivo)
        return arquivo

    def validate_documento_assinado(self, arquivo):
        return self._validar('documento_assinado', arquivo)

    def validate_foto_cliente(self, arquivo):
        return self._validar('foto_cliente', arquivo)

    def validate_imagem_imei(self, arquivo):
        return self._validar('imagem_imei', arquivo)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                'Envie ao menos um arquivo: documento_assinado, foto_cliente ou imagem_imei.'
            )
        venda = self.context.get('venda')
        if 'imagem_imei' in attrs and venda is not None and not venda.tem_iphone:
            raise serializers.ValidationError({'imagem_imei': ['A imagem do IMEI só é aceita em vendas de iPhone.']})
        return attrs


class AutorizacaoGerenteSerializer(serializers.Serializer):
    usuario = serializers.CharField(max_length=150)
    senha = serializers.CharField(max_length=128, trim_whitespace=False)
    venda = serializers.IntegerField(required=False)
    loja = serializers.IntegerField(required=False)
