"""Serializers de usuários (leitura e entrada). `is_superuser`/`is_staff` são só leitura."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from backoffice_api.nucleo.permissoes import PERMISSAO_ACESSO
from vendas.models import Loja

from ..regras import codigo_permissao, motivo_para_nao_gerenciar, permissoes_efetivas
from ..rotulos import rotulo_permissao

User = get_user_model()
TAMANHO_MAXIMO_MOTIVO = 1000


class AdmLojaResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loja
        fields = ['id', 'nome']


class AdmGrupoResumoSerializer(serializers.ModelSerializer):
    nome = serializers.CharField(source='name')

    class Meta:
        model = Group
        fields = ['id', 'nome']


class AdmPermissaoResumoSerializer(serializers.ModelSerializer):
    codigo = serializers.SerializerMethodField()
    nome = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ['id', 'codigo', 'nome']

    def get_codigo(self, obj) -> str:
        return codigo_permissao(obj)

    def get_nome(self, obj) -> str:
        return rotulo_permissao(obj)


def _nome_completo(user) -> str:
    return user.get_full_name() or user.username


class AdmUsuarioListaSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source='username')
    nome_completo = serializers.SerializerMethodField()
    ativo = serializers.BooleanField(source='is_active')
    grupos = serializers.SerializerMethodField()
    loja_principal = AdmLojaResumoSerializer(source='loja', read_only=True)
    ultimo_acesso = serializers.DateTimeField(source='last_login')

    class Meta:
        model = User
        fields = ['id', 'usuario', 'nome_completo', 'email', 'ativo', 'grupos', 'loja_principal', 'ultimo_acesso']

    def get_nome_completo(self, obj) -> str:
        return _nome_completo(obj)

    def get_grupos(self, obj) -> list[str]:
        return sorted(g.name for g in obj.groups.all())


class AdmUsuarioDetalheSerializer(AdmUsuarioListaSerializer):
    """Contexto: `editor`, `minhas` (permissões de quem consulta) e `escopo` (ids ou None)."""

    nome = serializers.CharField(source='first_name')
    sobrenome = serializers.CharField(source='last_name')
    superusuario = serializers.BooleanField(source='is_superuser')
    staff = serializers.BooleanField(source='is_staff')
    criado_em = serializers.DateTimeField(source='date_joined')
    grupos = AdmGrupoResumoSerializer(source='groups', many=True, read_only=True)
    permissoes = AdmPermissaoResumoSerializer(source='user_permissions', many=True, read_only=True)
    lojas = serializers.SerializerMethodField()
    lojas_gerenciadas = serializers.SerializerMethodField()
    acesso_backoffice = serializers.SerializerMethodField()
    pode_editar = serializers.SerializerMethodField()
    motivo_bloqueio_edicao = serializers.SerializerMethodField()

    class Meta(AdmUsuarioListaSerializer.Meta):
        fields = [
            'id', 'usuario', 'nome', 'sobrenome', 'nome_completo', 'email', 'ativo', 'superusuario', 'staff',
            'ultimo_acesso', 'criado_em', 'grupos', 'permissoes', 'loja_principal', 'lojas',
            'lojas_gerenciadas', 'acesso_backoffice', 'pode_editar', 'motivo_bloqueio_edicao',
        ]

    def _lojas_visiveis(self, lojas) -> list:
        escopo = self.context.get('escopo')
        visiveis = [loja for loja in lojas if escopo is None or loja.pk in escopo]
        return AdmLojaResumoSerializer(sorted(visiveis, key=lambda loja: loja.nome), many=True).data

    @extend_schema_field(AdmLojaResumoSerializer(many=True))
    def get_lojas(self, obj) -> list:
        return self._lojas_visiveis(obj.lojas.all())

    @extend_schema_field(AdmLojaResumoSerializer(many=True))
    def get_lojas_gerenciadas(self, obj) -> list:
        return self._lojas_visiveis(obj.lojas_gerenciadas.all())

    def get_acesso_backoffice(self, obj) -> bool:
        return obj.is_superuser or PERMISSAO_ACESSO in permissoes_efetivas(obj)

    def get_motivo_bloqueio_edicao(self, obj) -> str | None:
        return motivo_para_nao_gerenciar(self.context['editor'], obj, self.context['minhas'])

    def get_pode_editar(self, obj) -> bool:
        return self.get_motivo_bloqueio_edicao(obj) is None


def _validar_unicos(dados: dict, instancia) -> None:
    erros = {}
    usuario = dados.get('username')
    if usuario and User.objects.filter(username__iexact=usuario).exclude(pk=getattr(instancia, 'pk', None)).exists():
        erros['usuario'] = ['Já existe um usuário com este nome de usuário.']
    email = dados.get('email')
    if email and User.objects.filter(email__iexact=email).exclude(pk=getattr(instancia, 'pk', None)).exists():
        erros['email'] = ['Já existe um usuário com este e-mail.']
    if erros:
        raise serializers.ValidationError(erros)


class AdmUsuarioEdicaoSerializer(serializers.Serializer):
    """Edição: todos os campos opcionais. Vínculos com lojas são conferidos no serviço."""

    usuario = serializers.CharField(source='username', max_length=150, required=False,
                                    validators=[UnicodeUsernameValidator()])
    nome = serializers.CharField(source='first_name', max_length=150, required=False, allow_blank=True)
    sobrenome = serializers.CharField(source='last_name', max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=254, required=False)
    grupos = serializers.PrimaryKeyRelatedField(many=True, queryset=Group.objects.all(), required=False)
    permissoes = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all(), required=False)
    lojas = serializers.PrimaryKeyRelatedField(many=True, queryset=Loja.objects.all(), required=False)
    lojas_gerenciadas = serializers.PrimaryKeyRelatedField(many=True, queryset=Loja.objects.all(), required=False)
    loja_principal = serializers.PrimaryKeyRelatedField(queryset=Loja.objects.all(), allow_null=True, required=False)

    def validate_email(self, valor: str) -> str:
        return valor.strip().lower()

    def validate(self, attrs: dict) -> dict:
        _validar_unicos(attrs, self.instance)
        return attrs


class AdmUsuarioCriacaoSerializer(AdmUsuarioEdicaoSerializer):
    email = serializers.EmailField(max_length=254)
    senha = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True)

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        if not attrs.get('username') and not (attrs.get('first_name') and attrs.get('last_name')):
            raise serializers.ValidationError({'usuario': ['Informe o usuário ou o nome e o sobrenome.']})
        candidato = User(
            username=attrs.get('username', ''), email=attrs.get('email', ''),
            first_name=attrs.get('first_name', ''), last_name=attrs.get('last_name', ''),
        )
        try:
            validate_password(attrs['senha'], candidato)
        except DjangoValidationError as erro:
            raise serializers.ValidationError({'senha': list(erro.messages)})
        return attrs


class AdmMotivoOpcionalSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=TAMANHO_MAXIMO_MOTIVO)


class AdmSenhaTemporariaSerializer(serializers.Serializer):
    senha_temporaria = serializers.CharField()
    mensagem = serializers.CharField()


class AdmResultadoBuscaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tipo = serializers.CharField()
    titulo = serializers.CharField()
    subtitulo = serializers.CharField()
    ativo = serializers.BooleanField()
