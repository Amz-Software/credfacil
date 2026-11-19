"""ViewSet de lojas, repasses da loja e replicação do QR code."""
from datetime import date
import logging

from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import LojaPermission
from api.serializers import (
    LojaListSerializer,
    LojaSerializer,
    RepasseCreateSerializer,
    RepasseSerializer,
    VendaSerializer,
)
from financeiro.models import Repasse
from vendas.models import Loja, Venda
from vendas.services import ErroDeNegocio
from vendas.services.lojas import replicar_qr_code_aplicativo, status_repasses_por_loja

from .comum import _resposta_de_erro


logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(tags=["Lojas"]),
    retrieve=extend_schema(tags=["Lojas"]),
    create=extend_schema(tags=["Lojas"]),
    update=extend_schema(tags=["Lojas"]),
    partial_update=extend_schema(tags=["Lojas"]),
    replicar_qrcode=extend_schema(tags=["Lojas"]),
)
class LojaViewSet(viewsets.ModelViewSet):
    queryset = Loja.objects.all()
    permission_classes = [LojaPermission]

    def get_queryset(self):
        user = self.request.user
        query = Loja.objects.all()
        loja_id = self.request.session.get("loja_id")
        search = self.request.query_params.get("search")
        filter_type = self.request.query_params.get("filter")

        if not user.has_perm("vendas.can_view_all_stores"):
            if loja_id:
                query = query.filter(id=loja_id)
            else:
                # Fallback para usuarios com lojas associadas
                user_lojas = getattr(user, "lojas", None)
                if user_lojas is not None and user_lojas.exists():
                    query = query.filter(id__in=user_lojas.values_list("id", flat=True))
                elif getattr(user, "loja_id", None):
                    query = query.filter(id=user.loja_id)
                else:
                    query = query.none()

        if search:
            query = query.filter(nome__icontains=search)

        if filter_type == "pendente":
            query = query.com_repasse_pendente()
        elif filter_type == "sem_pendente":
            query = query.sem_repasse_pendente()

        return query.order_by("nome")

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("filter", OpenApiTypes.STR, required=False, description="pendente|sem_pendente"),
        ],
        responses=LojaListSerializer,
    )
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        lojas = list(page if page is not None else queryset)
        context = {
            **self.get_serializer_context(),
            "repasses_status": status_repasses_por_loja(lojas),
        }
        data = LojaListSerializer(lojas, many=True, context=context).data
        return self.get_paginated_response(data) if page is not None else Response(data)

    @extend_schema(responses=LojaSerializer)
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == "list":
            return LojaListSerializer
        return LojaSerializer

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)

    def retrieve(self, request, *args, **kwargs):
        loja = self.get_object()
        data_inicio = request.query_params.get("data_inicio", "")
        data_fim = request.query_params.get("data_fim", "")
        di = parse_date(data_inicio) if data_inicio else None
        df = parse_date(data_fim) if data_fim else None

        can_view_repasse = request.user.has_perm("financeiro.view_repasse")
        can_create_repasse = request.user.has_perm("financeiro.add_repasse")

        repasses_qs = Repasse.objects.filter(loja=loja).select_related("criado_por") if can_view_repasse else Repasse.objects.none()
        repasse_paginator = Paginator(repasses_qs, 10)
        repasse_page = repasse_paginator.get_page(request.query_params.get("repasse_page"))

        vendas_qs = Venda.objects.filter(loja=loja, is_deleted=False).select_related("cliente")
        if di:
            vendas_qs = vendas_qs.filter(data_venda__date__gte=di)
        if df:
            vendas_qs = vendas_qs.filter(data_venda__date__lte=df)

        total_vendas = vendas_qs.aggregate(qtd=Count("id"))["qtd"] or 0
        valor_total = vendas_qs.aggregate(val=Sum("pagamentos__valor"))["val"] or 0

        venda_paginator = Paginator(vendas_qs.order_by("-data_venda"), 10)
        venda_page = venda_paginator.get_page(request.query_params.get("venda_page"))

        status_list = []
        repasse_atrasados = 0
        if can_view_repasse:
            status_list, _ = loja.get_repasses_status(meses_atras=1)
            if di:
                status_list = [r for r in status_list if r["data"] >= di]
            if df:
                status_list = [r for r in status_list if r["data"] <= df]

            repasse_atrasados = sum(1 for r in status_list if not r["feito"] and r["data"] < date.today())
        kpi_valor_repasse = loja.calcular_valor_repasse(di, df)

        payload = {
            "loja": LojaSerializer(loja, context={"request": request}).data,
            "contrato": loja.contrato or None,
            "repasses": {
                "count": repasse_paginator.count,
                "num_pages": repasse_paginator.num_pages,
                "page": repasse_page.number,
                "results": RepasseSerializer(repasse_page, many=True).data,
            },
            "vendas": {
                "count": venda_paginator.count,
                "num_pages": venda_paginator.num_pages,
                "page": venda_page.number,
                "results": VendaSerializer(venda_page, many=True).data,
            },
            "data_inicio": data_inicio,
            "data_fim": data_fim,
            "repasse_status_list": status_list,
            "repasse_atrasados": repasse_atrasados,
            "today": date.today(),
            "kpi_valor_repasse": kpi_valor_repasse,
            "kpi": {
                "qtd_vendas": total_vendas,
                "valor_total": valor_total,
                "valor_repasse": kpi_valor_repasse,
            },
            "acessos": {
                "pode_editar_loja": request.user.has_perm("vendas.change_loja"),
                "pode_criar_repasse": can_create_repasse,
                "pode_ver_repasse": can_view_repasse,
                "can_view_all_stores": request.user.has_perm("vendas.can_view_all_stores"),
            },
        }

        return Response(payload)

    @action(detail=True, methods=["get", "post"], url_path="repasses")
    @extend_schema(
        request=RepasseCreateSerializer,
        responses={200: RepasseSerializer(many=True), 201: RepasseSerializer, 403: OpenApiTypes.OBJECT},
    )
    def repasses(self, request, pk=None):
        loja = self.get_object()

        if request.method == "GET":
            if not request.user.has_perm("financeiro.view_repasse"):
                return Response({"detail": "Sem permissao para visualizar repasses."}, status=status.HTTP_403_FORBIDDEN)

            repasses_qs = Repasse.objects.filter(loja=loja).select_related("criado_por")
            paginator = Paginator(repasses_qs, 10)
            page = paginator.get_page(request.query_params.get("repasse_page"))
            return Response(
                {
                    "count": paginator.count,
                    "num_pages": paginator.num_pages,
                    "page": page.number,
                    "results": RepasseSerializer(page, many=True).data,
                }
            )

        if not request.user.has_perm("financeiro.add_repasse"):
            return Response({"detail": "Sem permissao para criar repasse."}, status=status.HTTP_403_FORBIDDEN)

        serializer = RepasseCreateSerializer(data=request.data, context={"request": request, "loja": loja})
        serializer.is_valid(raise_exception=True)
        repasse = serializer.save()
        return Response(RepasseSerializer(repasse).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="replicar-qrcode")
    @extend_schema(
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def replicar_qrcode(self, request, pk=None):
        loja = self.get_object()
        if not request.user.has_perm("vendas.change_loja"):
            return Response({"detail": "Sem permissao."}, status=status.HTTP_403_FORBIDDEN)

        try:
            replicar_qr_code_aplicativo(loja)
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response({"detail": "QR Code e código do aplicativo replicados com sucesso."})
