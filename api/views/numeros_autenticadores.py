"""Números autenticadores (ANALISTA/ADMINISTRADOR)."""
import logging

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from api.serializers import NumeroAutenticadorSerializer
from vendas.models import NumeroAutenticador


logger = logging.getLogger(__name__)


class NumeroAutenticadorPermission(IsAuthenticated):
    """Somente ANALISTA e ADMINISTRADOR (e superuser) podem gerenciar números autenticadores."""

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return (
                request.user.is_superuser
                or request.user.groups.filter(name__in=['ANALISTA', 'ADMINISTRADOR']).exists()
            )
        return (
            request.user.is_superuser
            or request.user.groups.filter(name__in=['ANALISTA', 'ADMINISTRADOR']).exists()
        )


class NumeroAutenticadorViewSet(viewsets.ModelViewSet):
    serializer_class = NumeroAutenticadorSerializer
    permission_classes = [NumeroAutenticadorPermission]

    def get_queryset(self):
        user = self.request.user
        qs = NumeroAutenticador.objects.all()

        loja_id = self.request.session.get('loja_id') or self.request.query_params.get('loja')
        if loja_id:
            qs = qs.filter(loja_id=loja_id)

        ativo = self.request.query_params.get('ativo')
        if ativo is not None:
            qs = qs.filter(ativo=ativo.lower() in ('1', 'true', 'yes'))

        return qs.order_by('numero')

    def perform_create(self, serializer):
        loja_id = self.request.session.get('loja_id')
        serializer.save(loja_id=loja_id, criado_por=self.request.user, modificado_por=self.request.user)

    def perform_update(self, serializer):
        serializer.save(modificado_por=self.request.user)
