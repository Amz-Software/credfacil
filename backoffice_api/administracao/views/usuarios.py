"""Usuários: lista (escopo de lojas), detalhe, criação, edição, desativar/reativar e senha.

Regras de segurança em `regras.py`: nunca grava `is_superuser`/`is_staff`; só concede
o que quem edita possui; não altera a si mesmo nem quem tem mais acesso; vínculos com
lojas só dentro do escopo de quem edita.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..base import AdministracaoViewSet, ids_escopo_de_escrita, lojas_para_filtro
from ..filtros import ler_ativo, ler_id, ler_texto, ordenar
from ..regras import exigir_pode_gerenciar, permissoes_efetivas
from ..senhas import gerar_senha_temporaria
from ..serializers import (
    AdmMotivoOpcionalSerializer,
    AdmSenhaTemporariaSerializer,
    AdmUsuarioCriacaoSerializer,
    AdmUsuarioDetalheSerializer,
    AdmUsuarioEdicaoSerializer,
    AdmUsuarioListaSerializer,
)
from ..servicos import atualizar_usuario, criar_usuario

User = get_user_model()
TAG = ['bo-administracao']
ORDENACAO_USUARIOS = {
    'usuario': 'username',
    'nome': 'first_name',
    'email': 'email',
    'ultimo_acesso': 'last_login',
    'criado_em': 'date_joined',
}


def usuarios_no_escopo(view):
    """Usuários vinculados (usuário, gerente ou loja principal) às lojas da requisição.

    Superusuários só aparecem para superusuário. Acesso global sem loja escolhida vê todos
    (inclusive quem ainda não tem loja).
    """
    editor = view.request.user
    usuarios = User.objects.all()
    if not editor.is_superuser:
        usuarios = usuarios.exclude(is_superuser=True)
    lojas = lojas_para_filtro(view)
    if lojas is not None:
        vinculados = User.objects.filter(
            Q(lojas__in=lojas) | Q(lojas_gerenciadas__in=lojas) | Q(loja__in=lojas)
        ).values('pk')
        usuarios = usuarios.filter(pk__in=vinculados)
    return usuarios


@extend_schema(tags=TAG)
class UsuarioViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, AdministracaoViewSet):
    permissoes = {
        'list': ['accounts.view_user'],
        'retrieve': ['accounts.view_user'],
        'create': ['accounts.add_user'],
        'partial_update': ['accounts.change_user'],
        'redefinir_senha': ['accounts.change_user'],
        'desativar': ['accounts.delete_user'],
        'reativar': ['accounts.delete_user'],
    }

    def minhas(self) -> set[str]:
        if not hasattr(self, '_minhas'):
            self._minhas = permissoes_efetivas(self.request.user)
        return self._minhas

    def get_queryset(self):
        usuarios = usuarios_no_escopo(self).select_related('loja').prefetch_related('groups')
        if self.action != 'list':
            return usuarios.prefetch_related('user_permissions__content_type', 'lojas', 'lojas_gerenciadas')
        params = self.request.query_params
        usuarios = usuarios.exclude(pk=self.request.user.pk)
        busca = ler_texto(params, 'busca')
        if busca:
            usuarios = usuarios.filter(
                Q(username__icontains=busca) | Q(first_name__icontains=busca)
                | Q(last_name__icontains=busca) | Q(email__icontains=busca)
            )
        grupo = ler_id(params, 'grupo')
        if grupo is not None:
            usuarios = usuarios.filter(groups__pk=grupo)
        loja = ler_id(params, 'loja')
        if loja is not None:
            usuarios = usuarios.filter(Q(lojas__pk=loja) | Q(lojas_gerenciadas__pk=loja) | Q(loja_id=loja)).distinct()
        ativo = ler_ativo(params, padrao='sim')
        if ativo is not None:
            usuarios = usuarios.filter(is_active=ativo)
        return ordenar(usuarios, params, ORDENACAO_USUARIOS, padrao=('first_name', 'username', 'pk'))

    def get_serializer_class(self):
        return AdmUsuarioListaSerializer if self.action == 'list' else AdmUsuarioDetalheSerializer

    def get_serializer_context(self) -> dict:
        contexto = super().get_serializer_context()
        contexto.update(editor=self.request.user, minhas=self.minhas(),
                        escopo=ids_escopo_de_escrita(self.request.user))
        return contexto

    def _detalhe(self, user) -> dict:
        recarregado = User.objects.select_related('loja').prefetch_related(
            'groups', 'user_permissions__content_type', 'lojas', 'lojas_gerenciadas'
        ).get(pk=user.pk)
        return AdmUsuarioDetalheSerializer(recarregado, context=self.get_serializer_context()).data

    def _alvo_gerenciavel(self):
        alvo = self.get_object()
        exigir_pode_gerenciar(self.request.user, alvo, self.minhas())
        return alvo

    @extend_schema(parameters=[
        OpenApiParameter('busca', OpenApiTypes.STR, description='Usuário, nome, sobrenome ou e-mail (contém).'),
        OpenApiParameter('grupo', OpenApiTypes.INT),
        OpenApiParameter('loja', OpenApiTypes.INT, description='Vinculados à loja (usuário, gerente ou principal).'),
        OpenApiParameter('ativo', OpenApiTypes.STR, enum=['sim', 'nao', 'todos'], description='Padrão: sim.'),
        OpenApiParameter('ordenar', OpenApiTypes.STR,
                         description='usuario, nome, email, ultimo_acesso, criado_em (- para decrescente).'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=AdmUsuarioCriacaoSerializer, responses={201: AdmUsuarioDetalheSerializer})
    def create(self, request):
        entrada = AdmUsuarioCriacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        user = criar_usuario(editor=request.user, minhas=self.minhas(), dados=entrada.validated_data,
                             escopo=ids_escopo_de_escrita(request.user))
        detalhe = self._detalhe(user)
        self.auditar('usuario_criado', objeto=user, descricao=f'Usuário {user.username}', dados={
            'grupos': [g['nome'] for g in detalhe['grupos']],
            'permissoes': [p['codigo'] for p in detalhe['permissoes']],
            'lojas': sorted(user.lojas.values_list('pk', flat=True)),
            'lojas_gerenciadas': sorted(user.lojas_gerenciadas.values_list('pk', flat=True)),
            'loja_principal': user.loja_id,
        })
        return Response(detalhe, status=status.HTTP_201_CREATED)

    @extend_schema(request=AdmUsuarioEdicaoSerializer, responses=AdmUsuarioDetalheSerializer)
    def partial_update(self, request, pk=None):
        alvo = self._alvo_gerenciavel()
        entrada = AdmUsuarioEdicaoSerializer(alvo, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        mudancas = atualizar_usuario(editor=request.user, minhas=self.minhas(), alvo=alvo,
                                     dados=entrada.validated_data, escopo=ids_escopo_de_escrita(request.user))
        if mudancas:
            self.auditar('usuario_alterado', objeto=alvo, descricao=f'Usuário {alvo.username}', dados=mudancas)
        return Response(self._detalhe(alvo))

    def _alterar_situacao(self, ativo: bool) -> Response:
        alvo = self._alvo_gerenciavel()
        entrada = AdmMotivoOpcionalSerializer(data=self.request.data)
        entrada.is_valid(raise_exception=True)
        if alvo.is_active != ativo:
            alvo.is_active = ativo
            alvo.save(update_fields=['is_active'])
            self.auditar('usuario_reativado' if ativo else 'usuario_desativado', objeto=alvo,
                         descricao=f'Usuário {alvo.username}', motivo=entrada.validated_data.get('motivo', ''))
        return Response(self._detalhe(alvo))

    @extend_schema(request=AdmMotivoOpcionalSerializer, responses=AdmUsuarioDetalheSerializer)
    @action(detail=True, methods=['post'])
    def desativar(self, request, pk=None):
        return self._alterar_situacao(False)

    @extend_schema(request=AdmMotivoOpcionalSerializer, responses=AdmUsuarioDetalheSerializer)
    @action(detail=True, methods=['post'])
    def reativar(self, request, pk=None):
        return self._alterar_situacao(True)

    @extend_schema(request=AdmMotivoOpcionalSerializer, responses=AdmSenhaTemporariaSerializer)
    @action(detail=True, methods=['post'], url_path='redefinir-senha')
    def redefinir_senha(self, request, pk=None):
        alvo = self._alvo_gerenciavel()
        entrada = AdmMotivoOpcionalSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        senha = gerar_senha_temporaria(alvo)
        alvo.set_password(senha)
        alvo.save(update_fields=['password'])
        self.auditar('senha_redefinida', objeto=alvo, descricao=f'Usuário {alvo.username}',
                     motivo=entrada.validated_data.get('motivo', ''))
        resposta = Response(AdmSenhaTemporariaSerializer({
            'senha_temporaria': senha,
            'mensagem': 'Anote e entregue a senha ao usuário: ela não será exibida de novo.',
        }).data)
        resposta['Cache-Control'] = 'no-store'
        return resposta
