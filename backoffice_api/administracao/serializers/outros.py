"""Serializers de grupos, permissões, auditoria e perfil."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from backoffice_api.models import RegistroAuditoria

from ..regras import codigo_permissao
from ..rotulos import acao_padrao, nome_do_app, nome_do_modelo, rotulo_permissao

User = get_user_model()


# --- permissões -------------------------------------------------------------------------------

class AdmPermissaoSerializer(serializers.ModelSerializer):
    codigo = serializers.SerializerMethodField()
    nome = serializers.SerializerMethodField()
    nome_original = serializers.CharField(source='name')
    app_label = serializers.CharField(source='content_type.app_label')
    app_nome = serializers.SerializerMethodField()
    modelo = serializers.CharField(source='content_type.model')
    modelo_nome = serializers.SerializerMethodField()
    acao = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ['id', 'codigo', 'codename', 'nome', 'nome_original', 'app_label', 'app_nome', 'modelo',
                  'modelo_nome', 'acao']

    def get_codigo(self, obj) -> str:
        return codigo_permissao(obj)

    def get_nome(self, obj) -> str:
        return rotulo_permissao(obj)

    def get_app_nome(self, obj) -> str:
        return nome_do_app(obj.content_type.app_label)

    def get_modelo_nome(self, obj) -> str:
        return nome_do_modelo(obj.content_type)

    def get_acao(self, obj) -> str | None:
        return acao_padrao(obj)


class AdmPermissaoMatrizSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    codename = serializers.CharField()
    nome = serializers.CharField()
    acao = serializers.CharField(allow_null=True)
    pode_conceder = serializers.BooleanField()


class AdmModeloMatrizSerializer(serializers.Serializer):
    modelo = serializers.CharField()
    nome = serializers.CharField()
    permissoes = AdmPermissaoMatrizSerializer(many=True)


class AdmAppMatrizSerializer(serializers.Serializer):
    app_label = serializers.CharField()
    nome = serializers.CharField()
    modelos = AdmModeloMatrizSerializer(many=True)


class AdmMatrizSerializer(serializers.Serializer):
    apps = AdmAppMatrizSerializer(many=True)


# --- grupos -----------------------------------------------------------------------------------

class AdmGrupoListaSerializer(serializers.ModelSerializer):
    """Contexto: `editor`, `minhas`. `total_*` vêm anotados na consulta."""

    nome = serializers.CharField(source='name')
    total_permissoes = serializers.IntegerField(read_only=True)
    total_usuarios = serializers.IntegerField(read_only=True)
    pode_editar = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = ['id', 'nome', 'total_permissoes', 'total_usuarios', 'pode_editar']

    def get_pode_editar(self, obj) -> bool:
        if self.context['editor'].is_superuser:
            return True
        return not ({codigo_permissao(p) for p in obj.permissions.all()} - self.context['minhas'])


class AdmGrupoDetalheSerializer(AdmGrupoListaSerializer):
    permissoes = serializers.SerializerMethodField()

    class Meta(AdmGrupoListaSerializer.Meta):
        fields = AdmGrupoListaSerializer.Meta.fields + ['permissoes']

    @extend_schema_field(AdmPermissaoSerializer(many=True))
    def get_permissoes(self, obj) -> list:
        ordenadas = sorted(obj.permissions.all(), key=lambda p: (p.content_type.app_label, p.content_type.model,
                                                                 p.codename))
        return AdmPermissaoSerializer(ordenadas, many=True).data


class AdmGrupoEntradaSerializer(serializers.Serializer):
    nome = serializers.CharField(max_length=150)
    permissoes = serializers.PrimaryKeyRelatedField(many=True, queryset=Permission.objects.all(), required=False)

    def validate_nome(self, valor: str) -> str:
        valor = valor.strip()
        repetidos = Group.objects.filter(name__iexact=valor)
        if self.instance is not None:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise serializers.ValidationError('Já existe um grupo com este nome.')
        return valor


# --- auditoria --------------------------------------------------------------------------------

class AdmRegistroAuditoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistroAuditoria
        fields = ['id', 'criado_em', 'usuario', 'usuario_nome', 'acao', 'objeto_tipo', 'objeto_id', 'descricao',
                  'motivo', 'dados', 'ip', 'user_agent']


# --- perfil -----------------------------------------------------------------------------------

class AdmPerfilSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source='username', read_only=True)
    nome = serializers.CharField(source='first_name', max_length=150, required=False, allow_blank=True)
    sobrenome = serializers.CharField(source='last_name', max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=254, required=False)
    senha_atual = serializers.CharField(max_length=128, trim_whitespace=False, write_only=True, required=False)

    class Meta:
        model = User
        fields = ['id', 'usuario', 'nome', 'sobrenome', 'email', 'senha_atual']
        read_only_fields = ['id']

    def validate_email(self, valor: str) -> str:
        valor = valor.strip().lower()
        if User.objects.filter(email__iexact=valor).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Já existe um usuário com este e-mail.')
        return valor

    def validate(self, attrs: dict) -> dict:
        senha = attrs.pop('senha_atual', None)
        novo_email = attrs.get('email')
        if novo_email is not None and novo_email != (self.instance.email or '').lower():
            if not senha or not self.instance.check_password(senha):
                raise serializers.ValidationError(
                    {'senha_atual': ['Informe a sua senha atual para trocar o e-mail.']}
                )
        return attrs
