"""Números autenticadores (CRUD); restrito a ANALISTA, ADMINISTRADOR ou superusuário."""
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.response import Response

from vendas.models import NumeroAutenticador

from ...nucleo.erros import VALIDACAO, ErroBackoffice
from ...nucleo.escopo import tem_acesso_global
from ...nucleo.permissoes import EmGrupo
from ..base import TAGS, LojasBaseViewSet
from ..serializers_repasses import NumeroAutenticadorSerializer

ANALISTA_OU_ADMIN = [EmGrupo('ANALISTA', 'ADMINISTRADOR')]


@extend_schema_view(
    list=extend_schema(tags=TAGS, parameters=[OpenApiParameter('busca', str), OpenApiParameter('ativo', bool)]),
    retrieve=extend_schema(tags=TAGS),
    create=extend_schema(tags=TAGS),
    partial_update=extend_schema(tags=TAGS),
    destroy=extend_schema(tags=TAGS),
)
class NumerosAutenticadoresViewSet(LojasBaseViewSet):
    permissoes = {acao: ANALISTA_OU_ADMIN for acao in ('list', 'retrieve', 'create', 'partial_update', 'destroy')}
    serializer_class = NumeroAutenticadorSerializer

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return NumeroAutenticador.objects.none()
        return self.filtrar_por_lojas(NumeroAutenticador.objects.select_related('loja'), 'loja')

    def get_serializer(self, *args, **kwargs):
        lojas = None if getattr(self, 'swagger_fake_view', False) else self.lojas()
        return NumeroAutenticadorSerializer(*args, lojas=lojas, **kwargs)

    def _obter(self, pk) -> NumeroAutenticador:
        return get_object_or_404(self.get_queryset(), pk=pk)

    def list(self, request):
        numeros = self.get_queryset()
        busca = (request.query_params.get('busca') or '').strip()
        if busca:
            numeros = numeros.filter(Q(numero__icontains=busca) | Q(descricao__icontains=busca))
        ativo = request.query_params.get('ativo')
        if ativo in ('true', '1', 'false', '0'):
            numeros = numeros.filter(ativo=ativo in ('true', '1'))
        return self.paginar(numeros.order_by('numero', 'id'))

    def paginar(self, queryset):
        pagina = self.paginate_queryset(queryset)
        return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self._obter(pk)).data)

    def _loja_padrao(self):
        """Sem `loja_id`: a loja escolhida em X-Loja; global sem loja escolhida grava sem loja."""
        lojas = self.lojas()
        cabecalho = (self.request.headers.get('X-Loja') or '').strip().lower()
        if cabecalho and cabecalho != 'todas':
            return lojas.first()
        if tem_acesso_global(self.request.user):
            return None
        if lojas.count() == 1:
            return lojas.first()
        raise ErroBackoffice('Informe a loja.', codigo=VALIDACAO, campos={'loja_id': ['Informe a loja.']})

    def create(self, request):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        loja = entrada.validated_data.pop('loja') if 'loja' in entrada.validated_data else self._loja_padrao()
        numero = NumeroAutenticador(loja=loja, **entrada.validated_data)
        numero.save(user=request.user)
        return Response(self.get_serializer(numero).data, status=201)

    def partial_update(self, request, pk=None):
        numero = self._obter(pk)
        entrada = self.get_serializer(numero, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        for campo, valor in entrada.validated_data.items():
            setattr(numero, campo, valor)
        numero.save(user=request.user)
        return Response(self.get_serializer(numero).data)

    def destroy(self, request, pk=None):
        numero = self._obter(pk)
        with transaction.atomic():
            self.auditar('numero_autenticador_removido', objeto=numero,
                         dados={'numero': numero.numero, 'descricao': numero.descricao, 'loja_id': numero.loja_id})
            numero.delete()
        return Response(status=204)
