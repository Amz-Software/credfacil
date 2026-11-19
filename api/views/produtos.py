"""Catálogo: produtos, parcelamentos e marcas."""
import logging

from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.permissions import ProdutoPermission
from api.serializers import MarcaSerializer, ParcelamentoSerializer, ProdutoSerializer
from produtos.models import Marca, Parcelamento, Produto
from vendas.models import Loja


logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(tags=["Produtos"]),
    retrieve=extend_schema(tags=["Produtos"]),
    create=extend_schema(tags=["Produtos"]),
    update=extend_schema(tags=["Produtos"]),
    partial_update=extend_schema(tags=["Produtos"]),
    ativar=extend_schema(tags=["Produtos"]),
    desativar=extend_schema(tags=["Produtos"]),
)
class ProdutoViewSet(viewsets.ModelViewSet):
    queryset = Produto.objects.all()
    serializer_class = ProdutoSerializer
    permission_classes = [ProdutoPermission]

    def get_queryset(self):
        if self.request.user.has_perm("produtos.view_all_produtos"):
            queryset = Produto.objects.all()
        else:
            loja_id = self.request.session.get("loja_id") or self.request.query_params.get("loja")
            
            if not loja_id and hasattr(self.request.user, "loja_id") and self.request.user.loja_id:
                loja_id = self.request.user.loja_id
            
            loja = Loja.objects.filter(id=loja_id).first() if loja_id else None
            if loja:
                queryset = loja.produtos_permitidos_qs()
            else:
                queryset = Produto.objects.filter(ativo=True).filter(
                    Q(marca__isnull=True) |
                    Q(marca__lojas_permitidas__isnull=True)
                ).distinct()

        search = self.request.query_params.get("search")
        marca = self.request.query_params.get("marca")
        if search:
            queryset = queryset.filter(nome__icontains=search)
        if marca:
            queryset = queryset.filter(marca_id=marca)

        return queryset.order_by("nome")

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("marca", OpenApiTypes.INT, required=False),
        ],
        responses=ProdutoSerializer,
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        loja_id = self.request.session.get("loja_id") or self.request.query_params.get("loja") or self.request.data.get("loja")
        if not loja_id and hasattr(self.request.user, "loja_id"):
            loja_id = self.request.user.loja_id
            
        if not loja_id:
            raise ValidationError({"detail": "Loja nao informada para vincular o produto."})
        serializer.save(loja_id=loja_id)

    @action(detail=True, methods=["post"], url_path="ativar")
    def ativar(self, request, pk=None):
        produto = self.get_object()
        produto.ativo = True
        produto.save()
        return Response({"detail": "Produto ativado com sucesso."})

    @action(detail=True, methods=["post"], url_path="desativar")
    def desativar(self, request, pk=None):
        produto = self.get_object()
        produto.ativo = False
        produto.save()
        return Response({"detail": "Produto desativado com sucesso."})


@extend_schema_view(
    list=extend_schema(tags=["Parcelamentos"]),
    retrieve=extend_schema(tags=["Parcelamentos"]),
    create=extend_schema(tags=["Parcelamentos"]),
    update=extend_schema(tags=["Parcelamentos"]),
    partial_update=extend_schema(tags=["Parcelamentos"]),
    destroy=extend_schema(tags=["Parcelamentos"]),
)
class ParcelamentoViewSet(viewsets.ModelViewSet):
    queryset = Parcelamento.objects.select_related("marca").all()
    serializer_class = ParcelamentoSerializer
    permission_classes = [ProdutoPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        marca_id = self.request.query_params.get("marca")
        if marca_id:
            qs = qs.filter(marca_id=marca_id)
        return qs

    def perform_create(self, serializer):
        loja_id = self.request.session.get("loja_id") or self.request.query_params.get("loja") or self.request.data.get("loja")
        if not loja_id and hasattr(self.request.user, "loja_id"):
            loja_id = self.request.user.loja_id
            
        if not loja_id:
            raise ValidationError({"detail": "Loja nao informada para vincular o parcelamento."})
        serializer.save(loja_id=loja_id)


@extend_schema_view(
    list=extend_schema(tags=["Marcas"]),
    retrieve=extend_schema(tags=["Marcas"]),
    create=extend_schema(tags=["Marcas"]),
    update=extend_schema(tags=["Marcas"]),
    partial_update=extend_schema(tags=["Marcas"]),
    destroy=extend_schema(tags=["Marcas"]),
)
class MarcaViewSet(viewsets.ModelViewSet):
    serializer_class = MarcaSerializer
    permission_classes = [ProdutoPermission]

    def get_queryset(self):
        loja_id = self.request.session.get("loja_id") or self.request.query_params.get("loja")

        # Somente marcas ativas na listagem para o React; detail/update retornam todas
        qs = Marca.objects.filter(ativo=True) if self.action == "list" else Marca.objects.all()

        if self.action == "list" and loja_id:
            # Usando annotate para evitar ambiguidade do LEFT JOIN com M2M:
            # - marcas sem nenhuma loja configurada (visíveis para todas as lojas)
            # - marcas que incluem especificamente esta loja
            qs = qs.annotate(
                _n_lojas_perm=Count("lojas_permitidas", distinct=True)
            ).filter(
                Q(_n_lojas_perm=0) | Q(lojas_permitidas__id=loja_id)
            ).distinct()

        return qs

    def perform_create(self, serializer):
        loja_id = self.request.session.get("loja_id") or self.request.query_params.get("loja") or self.request.data.get("loja")
        if not loja_id and hasattr(self.request.user, "loja_id"):
            loja_id = self.request.user.loja_id
            
        if not loja_id:
            raise ValidationError({"detail": "Loja nao informada para vincular a marca."})
        serializer.save(loja_id=loja_id)

    @action(detail=True, methods=["get"], url_path="produtos")
    def produtos(self, request, pk=None):
        marca = self.get_object()

        if request.user.has_perm("produtos.view_all_produtos"):
            queryset = Produto.objects.filter(marca=marca)
        else:
            queryset = Produto.objects.filter(marca=marca, ativo=True)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(nome__icontains=search)

        serializer = ProdutoSerializer(queryset.order_by("nome"), many=True)
        return Response(serializer.data)
