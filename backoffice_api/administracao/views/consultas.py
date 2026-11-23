"""Permissões (lista e matriz), auditoria, meu perfil e provedor de busca global."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response

from backoffice_api.models import RegistroAuditoria
from backoffice_api.nucleo.permissoes import QualquerPermissao

from ..base import AdministracaoAPIView
from ..filtros import ler_data, ler_id, ler_texto, ordenar
from ..regras import permissoes_efetivas
from ..rotulos import matriz_permissoes
from ..serializers import (
    AdmMatrizSerializer,
    AdmPerfilSerializer,
    AdmPermissaoSerializer,
    AdmRegistroAuditoriaSerializer,
    AdmResultadoBuscaSerializer,
)
from .usuarios import usuarios_no_escopo

User = get_user_model()
TAG = ['bo-administracao']
VER_AUDITORIA = 'backoffice_api.ver_auditoria'
LIMITE_BUSCA = 8
TAMANHO_MINIMO_TERMO = 2
ORDENACAO_PERMISSOES = {'app': 'content_type__app_label', 'modelo': 'content_type__model', 'codename': 'codename'}
ORDENACAO_AUDITORIA = {'criado_em': 'criado_em', 'acao': 'acao', 'usuario_nome': 'usuario_nome'}


@extend_schema(tags=TAG, parameters=[
    OpenApiParameter('busca', OpenApiTypes.STR, description='Nome, codename ou app (contém).'),
    OpenApiParameter('app', OpenApiTypes.STR, description='app_label exato.'),
    OpenApiParameter('ordenar', OpenApiTypes.STR, description='app, modelo, codename (- para decrescente).'),
], responses=AdmPermissaoSerializer(many=True))
class PermissoesView(AdministracaoAPIView):
    permissoes = {'GET': ['auth.view_permission']}

    def get(self, request):
        params = request.query_params
        consulta = Permission.objects.select_related('content_type')
        busca = ler_texto(params, 'busca')
        if busca:
            consulta = consulta.filter(
                Q(name__icontains=busca) | Q(codename__icontains=busca) | Q(content_type__app_label__icontains=busca)
            )
        app = ler_texto(params, 'app')
        if app:
            consulta = consulta.filter(content_type__app_label=app)
        consulta = ordenar(consulta, params, ORDENACAO_PERMISSOES,
                           padrao=('content_type__app_label', 'content_type__model', 'codename'))
        return self.paginar(consulta, AdmPermissaoSerializer)


@extend_schema(tags=TAG, responses=AdmMatrizSerializer)
class MatrizPermissoesView(AdministracaoAPIView):
    """Permissões agrupadas por app → modelo, com `pode_conceder` para quem consulta."""

    permissoes = {'GET': [QualquerPermissao(
        'auth.view_permission', 'auth.view_group', 'auth.add_group', 'auth.change_group',
        'accounts.add_user', 'accounts.change_user',
    )]}

    def get(self, request):
        concediveis = None if request.user.is_superuser else permissoes_efetivas(request.user)
        return Response({'apps': matriz_permissoes(Permission.objects.all(), concediveis=concediveis)})


@extend_schema(tags=TAG, parameters=[
    OpenApiParameter('usuario', OpenApiTypes.INT),
    OpenApiParameter('acao', OpenApiTypes.STR),
    OpenApiParameter('objeto_tipo', OpenApiTypes.STR, description='Ex.: accounts.user'),
    OpenApiParameter('objeto_id', OpenApiTypes.STR),
    OpenApiParameter('data_inicio', OpenApiTypes.DATE),
    OpenApiParameter('data_fim', OpenApiTypes.DATE),
    OpenApiParameter('busca', OpenApiTypes.STR, description='Usuário, ação, descrição ou motivo (contém).'),
    OpenApiParameter('ordenar', OpenApiTypes.STR, description='criado_em, acao, usuario_nome (padrão: -criado_em).'),
], responses=AdmRegistroAuditoriaSerializer(many=True))
class AuditoriaView(AdministracaoAPIView):
    permissoes = {'GET': [VER_AUDITORIA]}

    def get(self, request):
        params = request.query_params
        registros = RegistroAuditoria.objects.all()
        usuario = ler_id(params, 'usuario')
        if usuario is not None:
            registros = registros.filter(usuario_id=usuario)
        for campo in ('acao', 'objeto_tipo', 'objeto_id'):
            valor = ler_texto(params, campo)
            if valor:
                registros = registros.filter(**{campo: valor})
        inicio, fim = ler_data(params, 'data_inicio'), ler_data(params, 'data_fim')
        if inicio:
            registros = registros.filter(criado_em__date__gte=inicio)
        if fim:
            registros = registros.filter(criado_em__date__lte=fim)
        busca = ler_texto(params, 'busca')
        if busca:
            registros = registros.filter(
                Q(usuario_nome__icontains=busca) | Q(acao__icontains=busca)
                | Q(descricao__icontains=busca) | Q(motivo__icontains=busca)
            )
        registros = ordenar(registros, params, ORDENACAO_AUDITORIA, padrao=('-criado_em', '-pk'))
        return self.paginar(registros, AdmRegistroAuditoriaSerializer)


@extend_schema(tags=TAG, responses=inline_serializer('AdmAcoesAuditoria', {'acoes': serializers.ListField(
    child=serializers.CharField())}))
class AcoesAuditoriaView(AdministracaoAPIView):
    permissoes = {'GET': [VER_AUDITORIA]}

    def get(self, request):
        acoes = RegistroAuditoria.objects.order_by('acao').values_list('acao', flat=True).distinct()
        return Response({'acoes': list(acoes)})


@extend_schema(tags=TAG)
class PerfilView(AdministracaoAPIView):
    """Dados do próprio usuário. Trocar o e-mail exige `senha_atual`; senha em /me/senha/."""

    permissoes = {'GET': [], 'PATCH': []}

    @extend_schema(responses=AdmPerfilSerializer)
    def get(self, request):
        return Response(AdmPerfilSerializer(request.user).data)

    @extend_schema(request=AdmPerfilSerializer, responses=AdmPerfilSerializer)
    def patch(self, request):
        user = request.user
        antes = {'nome': user.first_name, 'sobrenome': user.last_name, 'email': user.email}
        entrada = AdmPerfilSerializer(user, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        user = entrada.save()
        depois = {'nome': user.first_name, 'sobrenome': user.last_name, 'email': user.email}
        mudancas = {c: {'antes': antes[c], 'depois': depois[c]} for c in antes if antes[c] != depois[c]}
        if mudancas:
            self.auditar('perfil_alterado', objeto=user, dados=mudancas)
        return Response(AdmPerfilSerializer(user).data)


@extend_schema(tags=TAG, parameters=[OpenApiParameter('termo', OpenApiTypes.STR, required=True)],
               responses=inline_serializer('AdmBuscaUsuarios', {'resultados': AdmResultadoBuscaSerializer(many=True)}))
class BuscaView(AdministracaoAPIView):
    """Provedor da busca global (Ctrl+K): usuários do escopo por nome, usuário ou e-mail."""

    permissoes = {'GET': ['accounts.view_user']}

    def get(self, request):
        termo = ler_texto(request.query_params, 'termo')
        if len(termo) < TAMANHO_MINIMO_TERMO:
            return Response({'resultados': []})
        usuarios = usuarios_no_escopo(self).filter(
            Q(username__icontains=termo) | Q(first_name__icontains=termo)
            | Q(last_name__icontains=termo) | Q(email__icontains=termo)
        ).order_by('-is_active', 'first_name', 'username')[:LIMITE_BUSCA]
        resultados = [{
            'id': u.pk,
            'tipo': 'usuario',
            'titulo': u.get_full_name() or u.username,
            'subtitulo': f'{u.username} · {u.email}',
            'ativo': u.is_active,
        } for u in usuarios]
        return Response({'resultados': AdmResultadoBuscaSerializer(resultados, many=True).data})
