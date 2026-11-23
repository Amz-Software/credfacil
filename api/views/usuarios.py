"""Usuários, grupos, permissões e login JWT."""
import logging

from django.contrib.auth.models import Group, Permission
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView

from accounts.models import User
from api.permissions import GroupPermission, UserPermission
from api.serializers import (
    CustomTokenObtainPairSerializer,
    GroupSerializer,
    PermissionSerializer,
    UserSerializer,
)


logger = logging.getLogger(__name__)


# --- User / Group / Permission ViewSets ---
@extend_schema_view(
    list=extend_schema(tags=['Users']),
    retrieve=extend_schema(tags=['Users']),
    create=extend_schema(tags=['Users']),
    update=extend_schema(tags=['Users']),
    partial_update=extend_schema(tags=['Users']),
)
class UserViewSet(ModelViewSet):
    queryset = User.objects.all().order_by('id')
    serializer_class = UserSerializer
    permission_classes = [UserPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['username', 'first_name', 'last_name', 'email']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        # Non-superusers see only users from the same loja or themselves
        if not user.is_superuser:
            if getattr(user, 'loja_id', None):
                qs = qs.filter(loja_id=user.loja_id)
            else:
                qs = qs.filter(id=user.id)
        return qs

    def list(self, request, *args, **kwargs):
        """Support both paginated responses and a raw array.

        - Default: paginated response (DRF pagination settings)
        - If query param `raw=1` or `all=1` present: return a plain list `[{...}, ...]`
        """
        raw = request.query_params.get('raw') or request.query_params.get('all')
        queryset = self.filter_queryset(self.get_queryset())

        if raw in ('1', 'true', 'True'):
            serializer = self.get_serializer(queryset, many=True)
            return Response(serializer.data)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='me')
    def me(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)


@extend_schema_view(
    list=extend_schema(tags=['Groups']),
    retrieve=extend_schema(tags=['Groups']),
    create=extend_schema(tags=['Groups']),
    update=extend_schema(tags=['Groups']),
    partial_update=extend_schema(tags=['Groups']),
)
class GroupViewSet(ModelViewSet):
    queryset = Group.objects.all().order_by('name')
    serializer_class = GroupSerializer
    permission_classes = [GroupPermission]
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']


@extend_schema_view(
    list=extend_schema(tags=['Permissions']),
    retrieve=extend_schema(tags=['Permissions']),
)
class PermissionViewSet(ReadOnlyModelViewSet):
    queryset = Permission.objects.select_related('content_type').all().order_by('content_type__app_label', 'codename')
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter]
    search_fields = ['codename', 'name']


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    View customizada para login JWT que retorna tokens + informações do usuário e lojas.
    """
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'


class LogoutJwtView(TokenBlacklistView):
    """`POST /api/token/logout/` com `{"refresh": "..."}`: põe o refresh na blacklist.

    Depois disso `/api/token/refresh/` recusa esse refresh (401). Não exige o
    access válido, para o logout funcionar mesmo com ele expirado.
    """
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'
