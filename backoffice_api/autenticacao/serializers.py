"""Serializers de autenticação e do usuário logado."""
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from vendas.models import Loja

from ..nucleo.escopo import escopo_lojas, tem_acesso_global
from ..nucleo.sessao import CHAVE_TROCAR_SENHA, expira_em


class LoginSerializer(serializers.Serializer):
    usuario = serializers.CharField(max_length=150)
    senha = serializers.CharField(max_length=128, trim_whitespace=False)


class TrocarSenhaSerializer(serializers.Serializer):
    senha_atual = serializers.CharField(max_length=128, trim_whitespace=False)
    nova_senha = serializers.CharField(max_length=128, trim_whitespace=False)
    confirmacao = serializers.CharField(max_length=128, trim_whitespace=False)

    def validate(self, attrs: dict) -> dict:
        user = self.context['user']
        if not user.check_password(attrs['senha_atual']):
            raise serializers.ValidationError({'senha_atual': ['Senha atual incorreta.']})
        if attrs['nova_senha'] != attrs['confirmacao']:
            raise serializers.ValidationError({'confirmacao': ['A confirmação não confere com a nova senha.']})
        if attrs['nova_senha'] == attrs['senha_atual']:
            raise serializers.ValidationError({'nova_senha': ['A nova senha precisa ser diferente da atual.']})
        try:
            validate_password(attrs['nova_senha'], user)
        except DjangoValidationError as erro:
            raise serializers.ValidationError({'nova_senha': list(erro.messages)})
        return attrs


class LojaResumoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Loja
        fields = ['id', 'nome']


def _iniciais(user) -> str:
    partes = [p for p in (user.first_name, user.last_name) if p]
    if not partes:
        return (user.username[:2] or '?').upper()
    return ''.join(p[0] for p in partes[:2]).upper()


def dados_me(user, request) -> dict:
    """Usuário logado, permissões efetivas e lojas do escopo (o que a SPA precisa)."""
    sessao = request.session
    return {
        'id': user.pk,
        'usuario': user.username,
        'nome': user.get_full_name() or user.username,
        'email': user.email,
        'iniciais': _iniciais(user),
        'grupos': sorted(user.groups.values_list('name', flat=True)),
        'permissoes': sorted(user.get_all_permissions()),
        'is_superuser': user.is_superuser,
        'lojas': LojaResumoSerializer(escopo_lojas(user).order_by('nome'), many=True).data,
        'pode_ver_todas_lojas': tem_acesso_global(user),
        'deve_trocar_senha': bool(sessao.get(CHAVE_TROCAR_SENHA, False)),
        'sessao': {
            'inatividade_minutos': settings.BACKOFFICE_SESSAO_INATIVIDADE_MIN,
            'expira_em': expira_em(request),
        },
    }
