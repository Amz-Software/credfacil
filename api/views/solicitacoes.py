"""ViewSet de solicitações de crédito (análise, app, iCloud, IMEI e geração da venda)."""
import logging

from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter, OpenApiTypes
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.pagination import SolicitacaoPagination
from api.permissions import SolicitacaoCreditoPermission
from api.serializers import ClienteSolicitacaoSerializer
from vendas.models import AnaliseCreditoCliente, Cliente
from vendas.services import ErroDeNegocio
from vendas.services.erros import PROIBIDO
from vendas.services.kpis import contar_por_status

from .solicitacoes_cadastro import CadastroDeSolicitacaoMixin
from .solicitacoes_etapas import EtapasDaAnaliseMixin
from .solicitacoes_regras import _filtro_busca_solicitacao


logger = logging.getLogger(__name__)


@extend_schema_view(
    list=extend_schema(tags=["Solicitacoes"]),
    retrieve=extend_schema(tags=["Solicitacoes"]),
    create=extend_schema(tags=["Solicitacoes"]),
    update=extend_schema(tags=["Solicitacoes"]),
    imei_telefone=extend_schema(tags=["Solicitacoes"]),
    status_app=extend_schema(tags=["Solicitacoes"]),
    instalar_app=extend_schema(tags=["Solicitacoes"]),
    confirmar_app=extend_schema(tags=["Solicitacoes"]),
    configurar_icloud=extend_schema(tags=["Solicitacoes"]),
    analista_confirm_icloud=extend_schema(tags=["Solicitacoes"]),
    analista_confirm_installed=extend_schema(tags=["Solicitacoes"]),
    informar_imei_analise=extend_schema(tags=["Solicitacoes"]),
    aprovar=extend_schema(tags=["Solicitacoes"]),
    reprovar=extend_schema(tags=["Solicitacoes"]),
    cancelar=extend_schema(tags=["Solicitacoes"]),
    gerar_venda=extend_schema(tags=["Solicitacoes"]),
)
class SolicitacaoCreditoViewSet(CadastroDeSolicitacaoMixin, EtapasDaAnaliseMixin, viewsets.ViewSet):
    permission_classes = [SolicitacaoCreditoPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = SolicitacaoPagination
    CAMPOS_FOTO_COMPROVANTES = {
        "documento_identificacao_frente",
        "documento_identificacao_verso",
        "comprovante_residencia",
        "foto_cliente",
    }

    def _base_queryset(self):
        return (
            Cliente.objects.select_related(
                "loja",
                "contato_adicional",
                "informacao_pessoal",
                "comprovantes",
                "analise_credito",
                "analise_credito__produto",
                "analise_credito__imei",
            )
        )

    def _lojas_usuario_ids(self, request):
        lojas_ids = set(request.user.lojas.values_list("id", flat=True))
        if getattr(request.user, "loja_id", None):
            lojas_ids.add(request.user.loja_id)
        return lojas_ids

    def _exigir_loja_do_usuario(self, request, cliente):
        """Usuário com loja principal só age sobre clientes dessa loja."""
        loja_do_usuario = getattr(request.user, "loja_id", None)
        if loja_do_usuario and cliente.loja_id != loja_do_usuario:
            raise ErroDeNegocio("Ação não autorizada para esta loja.", codigo=PROIBIDO)

    def _usuario_pode_acessar_cliente(self, request, cliente):
        if request.user.has_perm("vendas.view_all_analise_credito"):
            return True
        return cliente.loja_id in self._lojas_usuario_ids(request)

    def _get_queryset(self, request):
        qs = self._base_queryset()
        search = request.query_params.get("search")
        analise_online = request.query_params.get("analise_online")
        status_app = request.query_params.get("status_app")
        loja_filter = request.query_params.get("loja")
        data_inicio = request.query_params.get("data_inicio")
        data_fim = request.query_params.get("data_fim")
        vendas_nao_finalizadas = request.query_params.get("vendas_nao_finalizadas")

        if status_app:
            qs = qs.filter(analise_credito__status_aplicativo=status_app).distinct()
        if search:
            qs = qs.filter(_filtro_busca_solicitacao(search))
        if analise_online == "1":
            qs = qs.filter(analise_credito__analise_online=True).distinct()
        elif analise_online == "0":
            qs = qs.filter(analise_credito__analise_online=False).distinct()

        status = request.query_params.get("status")
        if status:
            qs = qs.filter(analise_credito__status=status).distinct()

        if data_inicio and data_fim:
            qs = qs.filter(analise_credito__data_analise__range=[data_inicio, data_fim]).distinct()
        elif data_inicio:
            qs = qs.filter(analise_credito__data_analise__gte=data_inicio).distinct()
        elif data_fim:
            qs = qs.filter(analise_credito__data_analise__lte=data_fim).distinct()

        if vendas_nao_finalizadas:
            qs = qs.filter(analise_credito__venda__isnull=True).distinct()

        # Aplicar filtro de loja baseado em permissões
        if not request.user.has_perm("vendas.view_all_analise_credito"):
            # Se loja foi especificada na query string, verificar se usuário tem acesso
            if loja_filter:
                # Verificar se usuário tem acesso à loja solicitada
                lojas_usuario = request.user.lojas.values_list('id', flat=True)
                if int(loja_filter) in lojas_usuario:
                    # Usuário tem acesso: usar filtro da query string
                    qs = qs.filter(loja_id=loja_filter)
                else:
                    # Usuário não tem acesso: usar loja da sessão
                    loja_id = request.session.get("loja_id")
                    if loja_id:
                        qs = qs.filter(loja_id=loja_id)
                    else:
                        qs = qs.none()
            else:
                # Sem filtro específico: usar loja da sessão
                loja_id = request.session.get("loja_id")
                if loja_id:
                    qs = qs.filter(loja_id=loja_id)
                else:
                    qs = qs.none()
        else:
            # Admin: respeitar filtro da query string se fornecido
            if loja_filter:
                qs = qs.filter(loja_id=loja_filter)

        return qs.order_by("-id")

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("status", OpenApiTypes.STR, required=False),
            OpenApiParameter("status_app", OpenApiTypes.STR, required=False),
            OpenApiParameter("analise_online", OpenApiTypes.STR, required=False, description="1|0"),
            OpenApiParameter("loja", OpenApiTypes.INT, required=False),
            OpenApiParameter("data_inicio", OpenApiTypes.DATE, required=False),
            OpenApiParameter("data_fim", OpenApiTypes.DATE, required=False),
            OpenApiParameter("vendas_nao_finalizadas", OpenApiTypes.STR, required=False),
        ],
        responses=ClienteSolicitacaoSerializer,
    )
    def list(self, request):
        qs = self._get_queryset(request)

        if request.user.has_perm("vendas.view_all_analise_credito"):
            analises = AnaliseCreditoCliente.objects.all()
        else:
            loja_id = request.session.get("loja_id")
            analises = AnaliseCreditoCliente.objects.filter(loja_id=loja_id)

        counts = analises.values("status").annotate(total=Count("id"))
        kpis = {item["status"]: item["total"] for item in counts}
        for code, _ in AnaliseCreditoCliente.STATUS_CHOICES:
            kpis.setdefault(code, 0)

        paginator = self.pagination_class()
        paginator.kpis = kpis
        paginator.status_choices = AnaliseCreditoCliente.STATUS_CHOICES
        paginator.status_app_choices = AnaliseCreditoCliente.STATUS_APP_CHOICES

        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            data = ClienteSolicitacaoSerializer(page, many=True).data
            return paginator.get_paginated_response(data)

        data = ClienteSolicitacaoSerializer(qs, many=True).data
        return Response(
            {
                "results": data,
                "kpis": kpis,
                "status_choices": AnaliseCreditoCliente.STATUS_CHOICES,
                "status_app_choices": AnaliseCreditoCliente.STATUS_APP_CHOICES,
            }
        )

    @extend_schema(responses=ClienteSolicitacaoSerializer)
    def retrieve(self, request, pk=None):
        cliente = get_object_or_404(
            Cliente.objects.select_related(
                "loja", "contato_adicional", "informacao_pessoal", "comprovantes", "analise_credito"
            ),
            pk=pk,
        )

        if not request.user.has_perm("vendas.view_all_analise_credito"):
            lojas_usuario = self._lojas_usuario_ids(request)

            loja_query = request.query_params.get("loja")
            if loja_query:
                try:
                    loja_query_id = int(loja_query)
                except (TypeError, ValueError):
                    return Response({"detail": "Parametro loja invalido."}, status=400)

                if loja_query_id not in lojas_usuario:
                    return Response({"detail": "Acao nao autorizada para esta loja."}, status=403)

                if cliente.loja_id != loja_query_id:
                    return Response({"detail": "Solicitacao nao pertence a loja informada."}, status=403)
            else:
                loja_sessao = request.session.get("loja_id")
                if loja_sessao:
                    if cliente.loja_id != loja_sessao and cliente.loja_id not in lojas_usuario:
                        return Response({"detail": "Acao nao autorizada para esta loja."}, status=403)
                elif cliente.loja_id not in lojas_usuario:
                    return Response({"detail": "Acao nao autorizada para esta loja."}, status=403)

        data = ClienteSolicitacaoSerializer(cliente).data
        return Response(data)

    @action(detail=False, methods=["get"], url_path="kpis")
    @extend_schema(
        parameters=[
            OpenApiParameter("loja", OpenApiTypes.INT, required=False, description="Filtrar KPIs por loja específica"),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "kpis": {
                        "type": "object",
                        "properties": {
                            "EA": {"type": "integer", "description": "Em análise"},
                            "A": {"type": "integer", "description": "Aprovado"},
                            "R": {"type": "integer", "description": "Reprovado"},
                            "C": {"type": "integer", "description": "Cancelado"},
                        },
                    },
                    "status_choices": {
                        "type": "array",
                        "items": {"type": "array"},
                    },
                    "status_app_choices": {
                        "type": "array",
                        "items": {"type": "array"},
                    },
                },
            }
        },
    )
    def kpis(self, request):
        """
        Retorna KPIs (contadores) de solicitações de crédito agrupados por status.
        
        Resposta inclui:
        - kpis: Objeto com contadores por status (EA, A, R, C)
        - status_choices: Array com opções de status disponíveis
        - status_app_choices: Array com opções de status do app
        
        Os KPIs respeitam as permissões do usuário. Se o usuário não tiver
        'vendas.view_all_analise_credito', os contadores se limitam à loja da sessão
        ou às lojas que o usuário tem acesso.
        """
        loja_filter = request.query_params.get("loja")
        
        if request.user.has_perm("vendas.view_all_analise_credito"):
            # Admin: pode ver tudo ou filtrar por loja específica
            analises = AnaliseCreditoCliente.objects.all()
            if loja_filter:
                analises = analises.filter(loja_id=loja_filter)
        else:
            # Não-admin: verificar se tem acesso à loja solicitada
            if loja_filter:
                # Verificar se usuário tem acesso à loja solicitada
                lojas_usuario = request.user.lojas.values_list('id', flat=True)
                if int(loja_filter) in lojas_usuario:
                    # Usuário tem acesso: usar filtro da query string
                    analises = AnaliseCreditoCliente.objects.filter(loja_id=loja_filter)
                else:
                    # Usuário não tem acesso: usar loja da sessão
                    loja_id = request.session.get("loja_id")
                    analises = AnaliseCreditoCliente.objects.filter(loja_id=loja_id)
            else:
                # Sem filtro específico: usar loja da sessão
                loja_id = request.session.get("loja_id")
                analises = AnaliseCreditoCliente.objects.filter(loja_id=loja_id)

        return Response(
            {
                "kpis": contar_por_status(analises),
                "status_choices": AnaliseCreditoCliente.STATUS_CHOICES,
                "status_app_choices": AnaliseCreditoCliente.STATUS_APP_CHOICES,
            }
        )
