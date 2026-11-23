"""Serializers de lojas: lista, detalhe, escrita e vendas do período.

Os campos legados `porcentagem_desconto_{4,6,8,10}` nunca são lidos nem gravados.
"""
import json

from django.contrib.auth import get_user_model
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from produtos.models import Produto
from vendas.models import Loja, Venda

from .arquivos import validar_imagem

TAMANHO_MAXIMO_CONTRATO = 200_000  # caracteres do JSON do Editor.js
DINHEIRO = {'max_digits': 14, 'decimal_places': 2}


def nome_usuario(user) -> str:
    return user.get_full_name() or user.get_username()


def pode_editar_campos_restritos(user) -> bool:
    """Como em loja_form.html: só ADMINISTRADOR ou superusuário."""
    return bool(user and (user.is_superuser or user.groups.filter(name='ADMINISTRADOR').exists()))


class UsuarioResumoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.SerializerMethodField()
    email = serializers.EmailField()

    def get_nome(self, user) -> str:
        return nome_usuario(user)


class ProdutoResumoSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    codigo = serializers.IntegerField(allow_null=True)


class SituacaoRepasseSerializer(serializers.Serializer):
    situacao = serializers.ChoiceField(choices=['pendente', 'em_dia', 'sem_dados'])
    atrasados = serializers.IntegerField()


class LojaListaSerializer(serializers.ModelSerializer):
    """Linha da lista; `repasses` vem do contexto (calendário calculado em lote)."""

    repasses = serializers.SerializerMethodField()

    class Meta:
        model = Loja
        fields = ['id', 'nome', 'cnpj', 'telefone', 'endereco', 'pode_vender_iphone', 'credfacil', 'repasses']

    @extend_schema_field(SituacaoRepasseSerializer)
    def get_repasses(self, loja) -> dict:
        return self.context.get('repasses', {}).get(loja.pk, {'situacao': 'sem_dados', 'atrasados': 0})


def _url_arquivo(loja: Loja, campo: str, rota: str) -> str | None:
    if not getattr(loja, campo):
        return None
    return reverse(f'backoffice_api:lojas:{rota}', args=[loja.pk])


class LojaDetalheSerializer(serializers.ModelSerializer):
    usuarios = UsuarioResumoSerializer(many=True, read_only=True)
    gerentes = UsuarioResumoSerializer(many=True, read_only=True)
    produtos_bloqueados = ProdutoResumoSerializer(many=True, read_only=True)
    url_logo = serializers.SerializerMethodField()
    url_qr_code = serializers.SerializerMethodField()

    class Meta:
        model = Loja
        fields = [
            'id', 'nome', 'cnpj', 'inscricao_estadual', 'endereco', 'telefone',
            'meta_vendas_diaria', 'meta_vendas_mensal', 'entrada_caixa_diaria',
            'mensagem_garantia', 'contrato', 'chave_pix', 'codigo_aplicativo',
            'pode_vender_iphone', 'credfacil', 'usuarios', 'gerentes', 'produtos_bloqueados',
            'url_logo', 'url_qr_code', 'criado_em', 'modificado_em',
        ]

    def get_url_logo(self, loja) -> str | None:
        return _url_arquivo(loja, 'logo_loja', 'loja-logo')

    def get_url_qr_code(self, loja) -> str | None:
        return _url_arquivo(loja, 'qr_code_aplicativo', 'loja-qrcode')


@extend_schema_field(OpenApiTypes.OBJECT)
class ContratoEditorJsField(serializers.Field):
    """JSON do Editor.js (objeto ou texto JSON, para envio em multipart)."""

    default_error_messages = {
        'invalido': 'Contrato inválido: envie o JSON do Editor.js com a lista `blocks`.',
        'grande': 'Contrato muito grande.',
    }

    def to_internal_value(self, data):
        if data in (None, ''):
            return {}
        if isinstance(data, str):
            if len(data) > TAMANHO_MAXIMO_CONTRATO:
                self.fail('grande')
            try:
                data = json.loads(data)
            except ValueError:
                self.fail('invalido')
        if not isinstance(data, dict):
            self.fail('invalido')
        if not data:
            return {}
        blocos = data.get('blocks')
        if not isinstance(blocos, list) or not all(
            isinstance(b, dict) and isinstance(b.get('type'), str) and isinstance(b.get('data', {}), dict)
            for b in blocos
        ):
            self.fail('invalido')
        if len(json.dumps(data)) > TAMANHO_MAXIMO_CONTRATO:
            self.fail('grande')
        return data

    def to_representation(self, value):
        return value


class LojaEscritaSerializer(serializers.ModelSerializer):
    """Criação e edição (JSON ou multipart). `pode_vender_iphone` só para ADMINISTRADOR."""

    contrato = ContratoEditorJsField(required=False)
    logo_loja = serializers.ImageField(required=False, validators=[validar_imagem])
    qr_code_aplicativo = serializers.ImageField(required=False, validators=[validar_imagem])
    usuarios = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=get_user_model().objects.filter(is_active=True),
    )
    gerentes = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=get_user_model().objects.filter(is_active=True),
    )
    produtos_bloqueados = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=Produto.objects.filter(ativo=True),
    )

    class Meta:
        model = Loja
        fields = [
            'nome', 'cnpj', 'inscricao_estadual', 'endereco', 'telefone',
            'meta_vendas_diaria', 'meta_vendas_mensal', 'entrada_caixa_diaria',
            'mensagem_garantia', 'contrato', 'chave_pix', 'codigo_aplicativo', 'pode_vender_iphone',
            'logo_loja', 'qr_code_aplicativo', 'usuarios', 'gerentes', 'produtos_bloqueados',
        ]

    def validate(self, attrs):
        desconhecidos = sorted(set(getattr(self, 'initial_data', {}) or {}) - set(self.fields))
        if desconhecidos:
            raise serializers.ValidationError({campo: ['Campo não editável.'] for campo in desconhecidos})
        user = self.context['request'].user
        if 'pode_vender_iphone' in attrs and not pode_editar_campos_restritos(user):
            raise serializers.ValidationError(
                {'pode_vender_iphone': ['Apenas administradores podem alterar esta configuração.']}
            )
        return attrs

    def _salvar(self, loja: Loja, dados: dict) -> Loja:
        relacoes = {campo: dados.pop(campo) for campo in ('usuarios', 'gerentes', 'produtos_bloqueados')
                    if campo in dados}
        for campo, valor in dados.items():
            setattr(loja, campo, valor)
        loja.save(user=self.context['request'].user)
        for campo, valor in relacoes.items():
            getattr(loja, campo).set(valor)
        return loja

    def create(self, validated_data):
        return self._salvar(Loja(), dict(validated_data))

    def update(self, instance, validated_data):
        return self._salvar(instance, dict(validated_data))


class VendaDoPeriodoSerializer(serializers.ModelSerializer):
    cliente = serializers.SerializerMethodField()
    valor_total = serializers.DecimalField(read_only=True, **DINHEIRO)

    class Meta:
        model = Venda
        fields = ['id', 'data_venda', 'cliente', 'repasse_logista', 'valor_total']

    @extend_schema_field({'type': 'object', 'properties': {'id': {'type': 'integer'}, 'nome': {'type': 'string'}}})
    def get_cliente(self, venda) -> dict:
        return {'id': venda.cliente_id, 'nome': venda.cliente.nome}
