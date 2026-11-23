"""Grupos com matriz de permissões: lista, detalhe, criação e edição (sem exclusão)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status
from rest_framework.response import Response

from backoffice_api.nucleo.permissoes import PermissaoNegada

from ..base import AdministracaoViewSet
from ..filtros import ler_texto, ordenar
from ..regras import MENSAGEM_GRUPO_MAIS_ACESSO, codigo_permissao, permissoes_efetivas, validar_concessao
from ..serializers import AdmGrupoDetalheSerializer, AdmGrupoEntradaSerializer, AdmGrupoListaSerializer

User = get_user_model()
ORDENACAO_GRUPOS = {'nome': 'name', 'total_usuarios': 'total_usuarios', 'total_permissoes': 'total_permissoes'}


def _contagem(through):
    subconsulta = (
        through.objects.filter(group_id=OuterRef('pk'))
        .order_by().values('group_id').annotate(total=Count('pk')).values('total')
    )
    return Coalesce(Subquery(subconsulta, output_field=IntegerField()), Value(0))


def _codigos(grupo) -> set[str]:
    return {codigo_permissao(p) for p in grupo.permissions.all()}


@extend_schema(tags=['bo-administracao'])
class GrupoViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, AdministracaoViewSet):
    permissoes = {
        'list': ['auth.view_group'],
        'retrieve': ['auth.view_group'],
        'create': ['auth.add_group'],
        'partial_update': ['auth.change_group'],
    }

    def minhas(self) -> set[str]:
        if not hasattr(self, '_minhas'):
            self._minhas = permissoes_efetivas(self.request.user)
        return self._minhas

    def _anotados(self):
        return Group.objects.annotate(
            total_permissoes=_contagem(Group.permissions.through),
            total_usuarios=_contagem(User.groups.through),
        ).prefetch_related('permissions__content_type')

    def get_queryset(self):
        grupos = self._anotados()
        if self.action != 'list':
            return grupos
        params = self.request.query_params
        busca = ler_texto(params, 'busca')
        if busca:
            grupos = grupos.filter(name__icontains=busca)
        return ordenar(grupos, params, ORDENACAO_GRUPOS, padrao=('name', 'pk'))

    def get_serializer_class(self):
        return AdmGrupoListaSerializer if self.action == 'list' else AdmGrupoDetalheSerializer

    def get_serializer_context(self) -> dict:
        contexto = super().get_serializer_context()
        contexto.update(editor=self.request.user, minhas=self.minhas())
        return contexto

    def _detalhe(self, grupo) -> dict:
        return AdmGrupoDetalheSerializer(self._anotados().get(pk=grupo.pk), context=self.get_serializer_context()).data

    @extend_schema(parameters=[
        OpenApiParameter('busca', OpenApiTypes.STR, description='Nome (contém).'),
        OpenApiParameter('ordenar', OpenApiTypes.STR,
                         description='nome, total_usuarios, total_permissoes (- para decrescente).'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=AdmGrupoEntradaSerializer, responses={201: AdmGrupoDetalheSerializer})
    def create(self, request):
        entrada = AdmGrupoEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        permissoes = entrada.validated_data.get('permissoes', [])
        validar_concessao(request.user, self.minhas(), permissoes=permissoes)
        with transaction.atomic():
            grupo = Group.objects.create(name=entrada.validated_data['nome'])
            grupo.permissions.set(permissoes)
            self.auditar('grupo_criado', objeto=grupo, descricao=f'Grupo {grupo.name}',
                         dados={'permissoes': sorted(_codigos(grupo))})
        return Response(self._detalhe(grupo), status=status.HTTP_201_CREATED)

    @extend_schema(request=AdmGrupoEntradaSerializer, responses=AdmGrupoDetalheSerializer)
    def partial_update(self, request, pk=None):
        grupo = self.get_object()
        antes = _codigos(grupo)
        if not request.user.is_superuser and antes - self.minhas():
            raise PermissaoNegada(MENSAGEM_GRUPO_MAIS_ACESSO)
        entrada = AdmGrupoEntradaSerializer(grupo, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        if 'permissoes' in dados:
            validar_concessao(request.user, self.minhas(), permissoes=dados['permissoes'])
        nome_antes = grupo.name
        with transaction.atomic():
            if 'nome' in dados:
                grupo.name = dados['nome']
                grupo.save(update_fields=['name'])
            if 'permissoes' in dados:
                grupo.permissions.set(dados['permissoes'])
            grupo = Group.objects.prefetch_related('permissions__content_type').get(pk=grupo.pk)
            depois = _codigos(grupo)
            mudancas = {}
            if grupo.name != nome_antes:
                mudancas['nome'] = {'antes': nome_antes, 'depois': grupo.name}
            if depois != antes:
                mudancas['permissoes_adicionadas'] = sorted(depois - antes)
                mudancas['permissoes_removidas'] = sorted(antes - depois)
            if mudancas:
                self.auditar('grupo_alterado', objeto=grupo, descricao=f'Grupo {grupo.name}', dados=mudancas)
        return Response(self._detalhe(grupo))
