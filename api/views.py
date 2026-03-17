from datetime import date
import re
import calendar
import json

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)

from financeiro.models import Repasse
from notifications.signals import notify

from notificacao.utils import enviar_ws_para_usuario
from vendas.forms import (
    AnaliseCreditoClienteForm,
    AnaliseCreditoClienteImeiForm,
    ClienteForm,
    ClienteTelefoneForm,
    ComprovantesClienteForm,
    ContatoAdicionalForm,
    InformacaoPessoalForm,
    FormaPagamentoEditFormSet,
    FormaPagamentoEdicaoEspecialFormSet,
    FormaPagamentoFormSet,
    ProdutoVendaEditFormSet,
    ProdutoVendaEdicaoEspecialFormSet,
    ProdutoVendaFormSet,
    VendaDocumentosForm,
    VendaEdicaoEspecialForm,
    VendaForm,
)
from vendas.models import (
    AnaliseCreditoCliente,
    Caixa,
    Cliente,
    Loja,
    Pagamento,
    Parcela,
    ProdutoVenda,
    TipoPagamento,
    Venda,
)
from produtos.models import Parcelamento, Produto, Marca
from estoque.models import EstoqueImei
from accounts.models import User

from .pagination import SolicitacaoPagination
from .permissions import LojaPermission, SolicitacaoCreditoPermission, ProdutoPermission, VendaPermission
from .serializers import (
    ClienteSolicitacaoSerializer,
    InformarImeiAnaliseInputSerializer,
    LojaListSerializer,
    LojaSerializer,
    MarcaSerializer,
    ParcelamentoSerializer,
    ProdutoSerializer,
    VendaSerializer,
    RepasseCreateSerializer,
    RepasseSerializer,
    SolicitacaoCreditoInputSerializer,
    SolicitacaoImeiTelefoneInputSerializer,
    VendaCreateUpdateSerializer,
    VendaDocumentosSerializer,
    VendaEdicaoEspecialInputSerializer,
    VendaTrocaProdutoSerializer,
)
from django.contrib.auth.models import Group, Permission
from .serializers import UserSerializer, GroupSerializer, PermissionSerializer
from .permissions import UserPermission
from rest_framework.permissions import IsAuthenticated
from rest_framework import mixins
from rest_framework import filters
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from drf_spectacular.utils import extend_schema, extend_schema_view


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def calcular_data_primeira_parcela(data_pagamento_str):
    hoje = timezone.now().date()
    dia_escolhido = int(data_pagamento_str)
    max_dias = 30
    ano, mes = hoje.year, hoje.month

    melhor_data = None
    maior_diferenca = -1

    for i in range(3):
        novo_mes = mes + i
        novo_ano = ano + (novo_mes - 1) // 12
        novo_mes = ((novo_mes - 1) % 12) + 1

        ultimo_dia_mes = calendar.monthrange(novo_ano, novo_mes)[1]
        dia_real = min(dia_escolhido, ultimo_dia_mes)

        data_candidata = date(novo_ano, novo_mes, dia_real)
        dias_ate_parcela = (data_candidata - hoje).days

        if 0 < dias_ate_parcela <= max_dias:
            if dias_ate_parcela > maior_diferenca:
                melhor_data = data_candidata
                maior_diferenca = dias_ate_parcela

    return melhor_data


def criar_parcelas(pagamento, loja):
    Parcela.objects.filter(pagamento=pagamento).delete()
    dia = pagamento.data_primeira_parcela.day

    for n in range(1, pagamento.parcelas + 1):
        month_offset = pagamento.data_primeira_parcela.month - 1 + (n - 1)
        ano = pagamento.data_primeira_parcela.year + month_offset // 12
        mes = month_offset % 12 + 1

        ultimo = calendar.monthrange(ano, mes)[1]
        venc_dia = min(dia, ultimo)
        data_venc = date(ano, mes, venc_dia)

        Parcela.objects.create(
            loja=loja,
            pagamento=pagamento,
            numero_parcela=n,
            valor=pagamento.valor_parcela,
            data_vencimento=data_venc,
            criado_por=pagamento.criado_por,
            modificado_por=pagamento.modificado_por,
        )


def _avisos_solicitacoes_existentes(*, cpf=None, rg=None, nome=None, telefone=None, exclude_cliente_id=None):
    filtros = Q()
    if cpf:
        filtros |= Q(cpf=cpf)
    if rg:
        filtros |= Q(rg=rg)
    if nome:
        filtros |= Q(nome__iexact=nome)
    if telefone:
        filtros |= Q(telefone=telefone)

    if not filtros:
        return None

    qs = Cliente.objects.filter(filtros).select_related("analise_credito")
    if exclude_cliente_id:
        qs = qs.exclude(pk=exclude_cliente_id)

    if not qs.exists():
        return None

    detalhes = []
    for cliente in qs[:5]:
        analise = getattr(cliente, "analise_credito", None)
        if analise:
            detalhes.append(
                f"Solicitacao #{analise.id} (Cliente {cliente.nome}, status {analise.get_status_display()})"
            )
        else:
            detalhes.append(f"Cliente #{cliente.id} ({cliente.nome})")

    total = qs.count()
    sufixo = f" +{total - len(detalhes)}" if total > len(detalhes) else ""
    mensagem = "Existem solicitacoes de credito com dados ja cadastrados (CPF, RG, Nome ou Telefone). "
    mensagem += "Encontradas: " + "; ".join(detalhes) + sufixo
    return mensagem


def _validar_parcelamento_iphone(form_analise_credito):
    """
    Valida se existem parcelamentos cadastrados para o produto iPhone selecionado.
    Retorna dict de erros (formato compatível com form.errors) ou None se válido.
    """
    produto = form_analise_credito.cleaned_data.get("produto")
    if not produto or not getattr(produto, "is_iphone", False):
        return None

    marca = getattr(produto, "marca", None)
    if not marca:
        return {
            "produto": [
                "Produto iPhone sem marca vinculada. Configure a marca do produto antes de criar a solicitacao."
            ]
        }

    numero_parcelas = form_analise_credito.cleaned_data.get("numero_parcelas")

    parcelamentos_marca = Parcelamento.objects.filter(marca=marca)

    if not parcelamentos_marca.exists():
        return {
            "numero_parcelas": [
                f"Nenhum parcelamento cadastrado para a marca '{marca.nome}'. "
                "Solicite ao administrador que cadastre os parcelamentos da marca antes de criar uma solicitacao de iPhone."
            ]
        }

    if numero_parcelas:
        try:
            numero_parcelas_int = int(numero_parcelas)
        except (TypeError, ValueError):
            return {"numero_parcelas": ["Numero de parcelas invalido."]}

        if parcelamentos_marca.filter(qtd_vezes=numero_parcelas_int).exists():
            return None

        return {
            "numero_parcelas": [
                f"Parcelamento de {numero_parcelas}x nao cadastrado para a marca '{marca.nome}'. "
                "Solicite ao administrador que cadastre o parcelamento correspondente."
            ]
        }

    return None


def _validar_marca_produto_solicitacao(request_data, produto):
    marca_id_raw = request_data.get("marca")

    if marca_id_raw in (None, ""):
        return {"marca": ["Este campo e obrigatorio."]}

    try:
        marca_id = int(marca_id_raw)
    except (TypeError, ValueError):
        return {"marca": ["Informe um id de marca valido."]}

    if not Marca.objects.filter(id=marca_id).exists():
        return {"marca": ["Marca informada nao encontrada."]}

    if not produto:
        return None

    if not produto.marca_id:
        return {"produto": ["O produto informado nao possui marca vinculada."]}

    if produto.marca_id != marca_id:
        return {
            "produto": [
                "O produto informado nao pertence a marca selecionada."
            ]
        }

    return None


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
        return super().list(request, *args, **kwargs)

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

        if not loja.qr_code_aplicativo or loja.codigo_aplicativo is None:
            return Response(
                {"detail": "Loja nao possui QR Code ou codigo do aplicativo configurado."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        lojas = Loja.objects.exclude(id=loja.id)
        for l in lojas:
            l.qr_code_aplicativo = loja.qr_code_aplicativo
            l.codigo_aplicativo = loja.codigo_aplicativo
            l.save(update_fields=["qr_code_aplicativo", "codigo_aplicativo"])

        return Response({"detail": "QR Code e codigo do aplicativo replicados com sucesso."})


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
class SolicitacaoCreditoViewSet(viewsets.ViewSet):
    permission_classes = [SolicitacaoCreditoPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = SolicitacaoPagination

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
            qs = qs.filter(nome__icontains=search)
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

        counts = analises.values("status").annotate(total=Count("id"))
        kpis = {item["status"]: item["total"] for item in counts}
        
        # Garantir que todos os status tenham um valor (0 se não houver)
        for code, _ in AnaliseCreditoCliente.STATUS_CHOICES:
            kpis.setdefault(code, 0)

        return Response(
            {
                "kpis": kpis,
                "status_choices": AnaliseCreditoCliente.STATUS_CHOICES,
                "status_app_choices": AnaliseCreditoCliente.STATUS_APP_CHOICES,
            }
        )

    @transaction.atomic
    @extend_schema(
        request=SolicitacaoCreditoInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo",
                value={
                    "marca": 1,
                    "nome": "Fulano",
                    "telefone": "11999999999",
                    "cpf": "12345678900",
                    "nascimento": "1990-01-01",
                    "rg": "1234567",
                    "cep": "01001000",
                    "endereco": "Rua A",
                    "bairro": "Centro",
                    "cidade": "Sao Paulo",
                    "profissao": "Vendedor",
                    "quantidade_dependentes": 0,
                    "recebe_auxilio": False,
                    "total_renda": "3500.00",
                    "nome_adicional": "Beltrano",
                    "contato": "11988887777",
                    "endereco_adicional": "Rua B",
                    "nome_pessoal": "Ciclano",
                    "contato_pessoal": "11977776666",
                    "endereco_pessoal": "Rua C",
                    "documento_identificacao_frente": "file",
                    "documento_identificacao_verso": "file",
                    "comprovante_residencia": "file",
                    "foto_cliente": "file",
                    "produto": 1,
                    "numero_parcelas": "6",
                    "data_pagamento": "10",
                    "analise_online": False,
                },
            )
        ],
    )
    def create(self, request):
        loja_id = request.session.get("loja_id")
        loja = Loja.objects.filter(id=loja_id).first() if loja_id else None

        form_cliente = ClienteForm(request.data, user=request.user)
        form_adicional = ContatoAdicionalForm(request.data, user=request.user)
        form_informacao = InformacaoPessoalForm(request.data, user=request.user)
        form_comprovantes = ComprovantesClienteForm(request.data, request.FILES, user=request.user)
        form_analise_credito = AnaliseCreditoClienteForm(
            request.data, user=request.user, loja=loja
        )

        if not all(
            [
                form_cliente.is_valid(),
                form_adicional.is_valid(),
                form_informacao.is_valid(),
                form_comprovantes.is_valid(),
                form_analise_credito.is_valid(),
            ]
        ):
            errors = {
                "cliente": form_cliente.errors,
                "contato_adicional": form_adicional.errors,
                "informacao_pessoal": form_informacao.errors,
                "comprovantes": form_comprovantes.errors,
                "analise_credito": form_analise_credito.errors,
            }
            return Response({"detail": "Erros de validacao.", "errors": errors}, status=400)

        aviso = _avisos_solicitacoes_existentes(
            cpf=form_cliente.cleaned_data.get("cpf"),
            rg=form_cliente.cleaned_data.get("rg"),
            nome=form_cliente.cleaned_data.get("nome"),
            telefone=form_cliente.cleaned_data.get("telefone"),
        )

        contato_adicional_val = form_adicional.cleaned_data.get("contato")
        contato_pessoal_val = form_informacao.cleaned_data.get("contato_pessoal")
        endereco_adicional_val = (form_adicional.cleaned_data.get("endereco_adicional") or "").strip().lower()
        endereco_pessoal_val = (form_informacao.cleaned_data.get("endereco_pessoal") or "").strip().lower()
        nome_adicional_val = (form_adicional.cleaned_data.get("nome_adicional") or "").strip().lower()
        nome_pessoal_val = (form_informacao.cleaned_data.get("nome_pessoal") or "").strip().lower()

        conflito = False
        conflito_erros = {}
        if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
            conflito = True
            conflito_erros["contato"] = "Contato Adicional nao pode ser igual ao Contato de Informacoes Pessoais."
            conflito_erros["contato_pessoal"] = "Contato de Informacoes Pessoais nao pode ser igual ao Contato Adicional."
        if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
            conflito = True
            conflito_erros["endereco_adicional"] = "Endereco Adicional nao pode ser igual ao Endereco de Informacoes Pessoais."
            conflito_erros["endereco_pessoal"] = "Endereco de Informacoes Pessoais nao pode ser igual ao Endereco Adicional."
        if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
            conflito = True
            conflito_erros["nome_adicional"] = "Nome Adicional nao pode ser igual ao Nome de Informacoes Pessoais."
            conflito_erros["nome_pessoal"] = "Nome de Informacoes Pessoais nao pode ser igual ao Nome Adicional."

        if conflito:
            return Response(
                {"detail": "Informacoes Pessoais e Contato Adicional nao podem ser iguais.", "errors": conflito_erros},
                status=400,
            )

        # Validação de parcelamento para produto iPhone
        erro_marca = _validar_marca_produto_solicitacao(
            request.data,
            form_analise_credito.cleaned_data.get("produto"),
        )
        if erro_marca:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_marca}},
                status=400,
            )

        erro_parcelamento = _validar_parcelamento_iphone(form_analise_credito)
        if erro_parcelamento:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_parcelamento}},
                status=400,
            )

        comprovantes = form_comprovantes.save()
        contato_adicional = form_adicional.save()
        informacao = form_informacao.save()

        if not loja_id:
            return Response({"detail": "Loja nao encontrada na sessao."}, status=400)

        cliente = form_cliente.save(commit=False)
        cliente.criado_por = request.user
        cliente.modificado_por = request.user
        cliente.loja = Loja.objects.get(id=loja_id)
        cliente.contato_adicional = contato_adicional
        cliente.informacao_pessoal = informacao
        cliente.comprovantes = comprovantes
        cliente.save()

        loja = Loja.objects.get(id=loja_id)
        analise = form_analise_credito.save(commit=False)
        analise.cliente = cliente
        analise.loja = loja
        analise.criado_por = request.user
        analise.modificado_por = request.user
        analise.save(user=request.user)

        payload = ClienteSolicitacaoSerializer(cliente).data
        if aviso:
            payload["warning"] = aviso
        return Response(payload, status=201)

    @transaction.atomic
    @extend_schema(
        request=SolicitacaoCreditoInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo update",
                value={
                    "marca": 1,
                    "nome": "Fulano",
                    "telefone": "11999999999",
                    "cpf": "12345678900",
                    "nascimento": "1990-01-01",
                    "rg": "1234567",
                    "cep": "01001000",
                    "endereco": "Rua A",
                    "bairro": "Centro",
                    "cidade": "Sao Paulo",
                    "profissao": "Vendedor",
                    "quantidade_dependentes": 0,
                    "recebe_auxilio": False,
                    "total_renda": "3500.00",
                    "nome_adicional": "Beltrano",
                    "contato": "11988887777",
                    "endereco_adicional": "Rua B",
                    "nome_pessoal": "Ciclano",
                    "contato_pessoal": "11977776666",
                    "endereco_pessoal": "Rua C",
                    "documento_identificacao_frente": "file",
                    "documento_identificacao_verso": "file",
                    "comprovante_residencia": "file",
                    "foto_cliente": "file",
                    "produto": 1,
                    "numero_parcelas": "6",
                    "data_pagamento": "10",
                    "analise_online": False,
                },
            )
        ],
    )
    def update(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        user = request.user

        is_analista = user.groups.filter(name="ANALISTA").exists()
        venda_gerada = cliente.analise_credito.venda is not None

        if not is_analista and not user.has_perm("vendas.change_status_analise") and not cliente.analise_credito.status == "EA":
            return Response(
                {"detail": "Somente solicitacoes em analise podem ser editadas."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if venda_gerada and not user.has_perm("vendas.can_edit_finished_sale"):
            return Response(
                {"detail": "Sem permissao para editar solicitacoes com venda gerada."},
                status=status.HTTP_403_FORBIDDEN,
            )

        loja_id = request.session.get("loja_id")
        loja = Loja.objects.filter(id=loja_id).first() if loja_id else None

        form_cliente = ClienteForm(request.data, instance=cliente, user=user)
        form_adicional = ContatoAdicionalForm(request.data, instance=cliente.contato_adicional, user=user)
        form_informacao = InformacaoPessoalForm(request.data, instance=cliente.informacao_pessoal, user=user)
        form_comprovantes = ComprovantesClienteForm(
            request.data, request.FILES, instance=cliente.comprovantes, user=user
        )
        form_analise_credito = AnaliseCreditoClienteForm(
            request.data, instance=cliente.analise_credito, user=user, loja=loja
        )

        if not all(
            [
                form_cliente.is_valid(),
                form_adicional.is_valid(),
                form_informacao.is_valid(),
                form_comprovantes.is_valid(),
                form_analise_credito.is_valid(),
            ]
        ):
            errors = {
                "cliente": form_cliente.errors,
                "contato_adicional": form_adicional.errors,
                "informacao_pessoal": form_informacao.errors,
                "comprovantes": form_comprovantes.errors,
                "analise_credito": form_analise_credito.errors,
            }
            return Response({"detail": "Erros de validacao.", "errors": errors}, status=400)

        aviso = _avisos_solicitacoes_existentes(
            cpf=form_cliente.cleaned_data.get("cpf"),
            rg=form_cliente.cleaned_data.get("rg"),
            nome=form_cliente.cleaned_data.get("nome"),
            telefone=form_cliente.cleaned_data.get("telefone"),
            exclude_cliente_id=cliente.pk,
        )

        contato_adicional_val = form_adicional.cleaned_data.get("contato")
        contato_pessoal_val = form_informacao.cleaned_data.get("contato_pessoal")
        endereco_adicional_val = (form_adicional.cleaned_data.get("endereco_adicional") or "").strip().lower()
        endereco_pessoal_val = (form_informacao.cleaned_data.get("endereco_pessoal") or "").strip().lower()
        nome_adicional_val = (form_adicional.cleaned_data.get("nome_adicional") or "").strip().lower()
        nome_pessoal_val = (form_informacao.cleaned_data.get("nome_pessoal") or "").strip().lower()

        conflito = False
        conflito_erros = {}
        if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
            conflito = True
            conflito_erros["contato"] = "Contato Adicional nao pode ser igual ao Contato de Informacoes Pessoais."
            conflito_erros["contato_pessoal"] = "Contato de Informacoes Pessoais nao pode ser igual ao Contato Adicional."
        if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
            conflito = True
            conflito_erros["endereco_adicional"] = "Endereco Adicional nao pode ser igual ao Endereco de Informacoes Pessoais."
            conflito_erros["endereco_pessoal"] = "Endereco de Informacoes Pessoais nao pode ser igual ao Endereco Adicional."
        if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
            conflito = True
            conflito_erros["nome_adicional"] = "Nome Adicional nao pode ser igual ao Nome de Informacoes Pessoais."
            conflito_erros["nome_pessoal"] = "Nome de Informacoes Pessoais nao pode ser igual ao Nome Adicional."

        if conflito:
            return Response(
                {"detail": "Informacoes Pessoais e Contato Adicional nao podem ser iguais.", "errors": conflito_erros},
                status=400,
            )

        # Validação de parcelamento para produto iPhone
        erro_marca = _validar_marca_produto_solicitacao(
            request.data,
            form_analise_credito.cleaned_data.get("produto"),
        )
        if erro_marca:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_marca}},
                status=400,
            )

        erro_parcelamento = _validar_parcelamento_iphone(form_analise_credito)
        if erro_parcelamento:
            return Response(
                {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_parcelamento}},
                status=400,
            )

        contato_adicional = form_adicional.save()
        informacao = form_informacao.save()
        comprovantes = form_comprovantes.save()
        form_analise_credito.save()

        cliente_obj = form_cliente.save(commit=False)
        cliente_obj.contato_adicional = contato_adicional
        cliente_obj.comprovantes = comprovantes
        cliente_obj.save(user=user)

        payload = ClienteSolicitacaoSerializer(cliente_obj).data
        if aviso:
            payload["warning"] = aviso
        return Response(payload)

    @action(detail=True, methods=["post"], url_path="imei-telefone")
    @extend_schema(
        request=SolicitacaoImeiTelefoneInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo imei",
                value={
                    "telefone": "11999999999",
                    "marca": 1,
                    "produto": 1,
                    "data_pagamento": "10",
                    "numero_parcelas": "6",
                    "imei": 123,
                },
            )
        ],
    )
    def imei_telefone(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        user = request.user

        form_cliente = ClienteTelefoneForm(request.data, instance=cliente, user=user)
        form_analise_credito = AnaliseCreditoClienteImeiForm(
            request.data, instance=cliente.analise_credito, user=user
        )

        if form_cliente.is_valid() and form_analise_credito.is_valid():
            erro_marca = _validar_marca_produto_solicitacao(
                request.data,
                form_analise_credito.cleaned_data.get("produto"),
            )
            if erro_marca:
                return Response(
                    {"detail": "Erros de validacao.", "errors": {"analise_credito": erro_marca}},
                    status=400,
                )

            form_analise_credito.save()
            cliente_obj = form_cliente.save(commit=False)
            cliente_obj.save(user=user)
            return Response(ClienteSolicitacaoSerializer(cliente_obj).data)

        errors = {
            "cliente": form_cliente.errors,
            "analise_credito": form_analise_credito.errors,
        }
        return Response({"detail": "Erros de validacao.", "errors": errors}, status=400)

    @action(detail=True, methods=["post"], url_path="status-app")
    @extend_schema(
        parameters=[OpenApiParameter("status_app", OpenApiTypes.STR, required=True)],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def status_app(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        new_status = request.data.get("status_app")
        analise_credito = cliente.analise_credito

        valid = dict(AnaliseCreditoCliente.STATUS_APP_CHOICES).keys()
        if new_status in valid:
            analise_credito.status_aplicativo = new_status
            analise_credito.save()
            return Response(
                {"detail": f"Status do aplicativo atualizado para {analise_credito.get_status_aplicativo_display()}."}
            )

        return Response({"detail": "Status invalido."}, status=400)

    @action(detail=True, methods=["post"], url_path="instalar-app")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def instalar_app(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise_credito = cliente.analise_credito

        loja_id = request.session.get("loja_id")
        if cliente.loja_id != loja_id:
            return Response({"detail": "Acao nao autorizada para esta loja."}, status=403)

        analise_credito.status_aplicativo = "C"
        analise_credito.save()
        return Response({"detail": "Status alterado para Confirmacao Pendente."})

    @action(detail=True, methods=["post"], url_path="confirmar-app")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def confirmar_app(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise_credito = cliente.analise_credito

        analise_credito.status_aplicativo = "C"
        analise_credito.save()

        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja

        verb = f"Vendedor confirmou instalacao do app para cliente {cliente_nome.capitalize()}."
        description = f"Aguardando analista informar IMEI. Loja: {loja.nome.capitalize()}."

        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=["ADMINISTRADOR", "ANALISTA"]).exclude(id=request.user.id)
        )

        for user in usuarios_para_notificar:
            notify.send(
                analise_credito,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            ultima_notificacao = user.notifications.unread().order_by("-timestamp").first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise_credito,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification="analise_credito_cliente",
                )

        return Response({"detail": "Instalacao confirmada. Aguardando analista informar IMEI."})

    @action(detail=True, methods=["post"], url_path="configurar-icloud")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def configurar_icloud(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito

        if not analise.email_icloud or not analise.senha_icloud:
            return Response({"detail": "Email e senha iCloud nao configurados na analise."}, status=400)

        analise.icloud_configurado_vendedor = True
        analise.save()

        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        verb = f"Vendedor configurou iCloud para cliente {cliente_nome.capitalize()}"
        description = f"iPhone da loja {loja.nome.capitalize()}. Aguardando confirmacao do analista."

        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=["ANALISTA", "ADMINISTRADOR"]).exclude(id=request.user.id)
        )
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            ultima_notificacao = user.notifications.unread().order_by("-timestamp").first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification="analise_credito_cliente",
                )

        return Response({"detail": f"Configuracao iCloud confirmada para {cliente.nome}."})

    @action(detail=True, methods=["post"], url_path="analista-confirm-icloud")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def analista_confirm_icloud(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito

        if not request.user.groups.filter(name="ANALISTA").exists():
            return Response({"detail": "Apenas analistas podem confirmar o iCloud."}, status=403)

        if not analise.icloud_configurado_vendedor:
            return Response({"detail": "Vendedor ainda nao confirmou a configuracao do iCloud."}, status=400)

        analise.icloud_confirmado_analista = True
        analise.save()

        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        verb = f"Analista confirmou configuracao iCloud para cliente {cliente_nome.capitalize()}"
        description = f"iPhone da loja {loja.nome.capitalize()}. Aguardando IMEI para gerar venda."

        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=["VENDEDOR", "ADMINISTRADOR", "ANALISTA"]).exclude(id=request.user.id)
        )
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            ultima_notificacao = user.notifications.unread().order_by("-timestamp").first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification="analise_credito_cliente",
                )

        return Response({"detail": f"Configuracao iCloud confirmada pelo analista para {cliente.nome}."})

    @action(detail=True, methods=["post"], url_path="analista-confirmar-instalacao")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def analista_confirm_installed(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise_credito = cliente.analise_credito

        if not request.user.groups.filter(name="ANALISTA").exists():
            return Response({"detail": "Apenas analistas podem confirmar a instalacao."}, status=403)

        if not analise_credito.imei:
            return Response({"detail": "IMEI deve estar informado para confirmar a instalacao."}, status=400)

        if analise_credito.status_aplicativo != "C":
            return Response(
                {"detail": 'Status do aplicativo deve estar "Aguardando Confirmacao" para confirmar a instalacao.'},
                status=400,
            )

        analise_credito.status_aplicativo = "I"
        analise_credito.save()

        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        verb = f"Analista confirmou instalacao do app para cliente {cliente_nome.capitalize()}."
        description = f"IMEI {analise_credito.imei.imei} da loja {loja.nome.capitalize()}. Venda liberada para geracao."

        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=["VENDEDOR", "ADMINISTRADOR", "ANALISTA"]).exclude(id=request.user.id)
        )
        for user in usuarios_para_notificar:
            notify.send(
                analise_credito,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            ultima_notificacao = user.notifications.unread().order_by("-timestamp").first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise_credito,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification="analise_credito_cliente",
                )

        return Response({"detail": f"Instalacao do app confirmada para {cliente.nome}."})

    @action(detail=True, methods=["post"], url_path="informar-imei-analise")
    @extend_schema(request=InformarImeiAnaliseInputSerializer, responses={200: OpenApiTypes.OBJECT})
    def informar_imei_analise(self, request, pk=None):
        if not request.user.groups.filter(name="ANALISTA").exists():
            return Response({"detail": "Apenas analistas podem informar IMEI."}, status=403)

        cliente = Cliente.objects.select_related("analise_credito__produto").get(pk=pk)
        analise = cliente.analise_credito
        if not analise:
            return Response({"detail": "Analise nao encontrada para este cliente."}, status=404)

        if analise.produto.is_iphone:
            if not analise.icloud_confirmado_analista:
                return Response(
                    {"detail": "So e possivel informar IMEI apos confirmar a configuracao do iCloud."},
                    status=400,
                )
        else:
            if analise.status_aplicativo != "C":
                return Response(
                    {"detail": "So e possivel informar IMEI apos o vendedor confirmar a instalacao do aplicativo."},
                    status=400,
                )

        imei_informado = request.data.get("imei_informado")
        if not imei_informado:
            return Response({"detail": "IMEI e obrigatorio."}, status=400)

        loja = Loja.objects.filter(id=request.session.get("loja_id")).first()
        if not loja:
            return Response({"detail": "Loja nao encontrada na sessao."}, status=400)

        estoque_imei_existente = EstoqueImei.objects.filter(
            imei=imei_informado,
            produto=analise.produto,
            loja=loja,
            vendido=False,
            cancelado=False,
        ).first()

        if estoque_imei_existente:
            analise.imei = estoque_imei_existente
            analise.imei_informado = imei_informado
            analise.save()
        else:
            try:
                novo_estoque_imei = EstoqueImei(
                    produto=analise.produto,
                    imei=imei_informado,
                    loja=loja,
                    vendido=False,
                    aplicativo_instalado=False,
                    cancelado=False,
                )
                novo_estoque_imei.save(user=request.user)
                analise.imei = novo_estoque_imei
                analise.imei_informado = imei_informado
                analise.save()
            except Exception as exc:
                return Response({"detail": f"Erro ao criar IMEI: {exc}"}, status=400)

        if not analise.produto.is_iphone:
            analise.status_aplicativo = "I"
            analise.save()

        imei_info = f"Imei {imei_informado}" if imei_informado else "IMEI nao informado"
        verb = f"Analista informou IMEI para cliente {cliente.nome.capitalize()}."
        description = f"{imei_info} da loja {loja.nome.capitalize()}. Venda liberada para geracao pelo vendedor."

        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=["ADMINISTRADOR", "ANALISTA"]).exclude(id=request.user.id)
        )
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            ultima_notificacao = user.notifications.unread().order_by("-timestamp").first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification="analise_credito_cliente",
                )

        return Response(
            {
                "detail": "IMEI informado com sucesso. Venda liberada para geracao.",
                "cliente_id": cliente.id,
                "analise_id": analise.id,
                "imei_informado": imei_informado,
            }
        )

    @action(detail=True, methods=["post"], url_path="aprovar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def aprovar(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito

        if analise.produto.is_iphone:
            if not analise.email_icloud or not analise.senha_icloud:
                return Response(
                    {"detail": "Para aprovar iPhone, e necessario informar Email e Senha iCloud na solicitacao."},
                    status=400,
                )

        analise.aprovar(user=request.user)
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        return Response({"detail": "Analise de credito aprovada com sucesso."})

    @action(detail=True, methods=["post"], url_path="reprovar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def reprovar(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito
        analise.reprovar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        return Response({"detail": "Analise de credito reprovada com sucesso."})

    @action(detail=True, methods=["post"], url_path="cancelar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def cancelar(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito
        analise.cancelar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        return Response({"detail": "Analise de credito cancelada com sucesso."})

    @action(detail=True, methods=["post"], url_path="gerar-venda")
    @extend_schema(request=None, responses=VendaSerializer)
    def gerar_venda(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        loja = Loja.objects.filter(id=request.session.get("loja_id")).first()
        credfacil = Loja.objects.filter(credfacil=True).first()

        if not credfacil or not loja or not cliente:
            return Response({"detail": "Loja ou cliente nao encontrado."}, status=400)

        cpf_limpo = re.sub(r"\D", "", cliente.cpf or "")
        vendas_com_poucas_parcelas = (
            Venda.objects.filter(cliente__cpf=cpf_limpo, is_deleted=False)
            .annotate(
                parcelas_pagas=Count(
                    "pagamentos__parcelas_pagamento",
                    filter=Q(
                        pagamentos__tipo_pagamento__nome__iexact="IPX",
                        pagamentos__parcelas_pagamento__pago=True,
                    ),
                    distinct=True,
                )
            )
            .filter(parcelas_pagas__lt=3)
        )

        if vendas_com_poucas_parcelas.exists():
            return Response(
                {
                    "detail": "Para gerar uma nova venda, cada venda anterior do mesmo CPF deve ter pelo menos 3 parcelas pagas."
                },
                status=400,
            )

        analise = cliente.analise_credito
        if not analise or analise.status != "A":
            return Response({"detail": "Analise de credito nao aprovada para o cliente."}, status=400)
        if not analise.imei:
            return Response({"detail": "Nenhum IMEI associado a analise de credito."}, status=400)
        if not getattr(analise.produto, "is_iphone", False) and analise.status_aplicativo != "I":
            return Response({"detail": "Aplicativo nao esta instalado."}, status=400)
        if analise.venda:
            return Response({"detail": "Essa solicitacao ja foi convertida em venda."}, status=400)

        caixa = Caixa.objects.filter(loja=analise.loja, data_fechamento__isnull=True).first()
        if not caixa:
            return Response(
                {"detail": f"Nenhum caixa aberto encontrado para a loja {analise.loja.nome}."},
                status=400,
            )

        produto = analise.produto
        imei = analise.imei

        if getattr(produto, "is_iphone", False):
            if not analise.email_icloud or not analise.senha_icloud:
                return Response(
                    {"detail": "Para gerar venda de iPhone, Email e Senha iCloud devem estar preenchidos."},
                    status=400,
                )
            if not analise.icloud_configurado_vendedor:
                return Response(
                    {"detail": "iCloud ainda nao foi configurado pelo vendedor."},
                    status=400,
                )
            if not analise.icloud_confirmado_analista:
                return Response(
                    {"detail": "iCloud nao confirmado pelo analista."},
                    status=400,
                )

        if ProdutoVenda.objects.filter(imei=imei.imei).exists():
            return Response(
                {"detail": f"IMEI {imei.imei} ja esta sendo usado em outra venda."}, status=400
            )

        try:
            with transaction.atomic():
                parcelas = int(analise.numero_parcelas)

                # Valor base obrigatório
                if not produto.valor:
                    return Response(
                        {"detail": "Produto sem valor base cadastrado."},
                        status=400,
                    )

                # Entrada informada pelo operador (deve ser >= entrada_cliente do produto)
                entrada_informada = analise.entrada_informada
                if entrada_informada is None:
                    entrada_informada = produto.entrada_cliente
                if entrada_informada < produto.entrada_cliente:
                    return Response(
                        {
                            "detail": (
                                f"Entrada informada (R$ {entrada_informada}) nao pode ser menor "
                                f"que a entrada minima do produto (R$ {produto.entrada_cliente})."
                            )
                        },
                        status=400,
                    )

                # Buscar percentual de juros na tabela Parcelamento vinculada à marca do produto
                marca = produto.marca
                parcelamento = Parcelamento.objects.filter(
                    marca=marca, qtd_vezes=parcelas
                ).first()
                if not parcelamento:
                    marca_nome = marca.nome if marca else "sem marca"
                    return Response(
                        {"detail": f"Nenhum parcelamento cadastrado para {parcelas}x na marca '{marca_nome}'."},
                        status=400,
                    )

                porcentagem_juros = parcelamento.porcentagem_juros
                porcentagem_desconto = parcelamento.porcentagem_desconto
                valor_financiado = produto.valor - entrada_informada
                valor_credfacil = valor_financiado + (valor_financiado * porcentagem_juros / 100)
                repasse_logista = produto.valor - entrada_informada
                valor_entrada = entrada_informada

                venda = Venda.objects.create(
                    loja=analise.loja,
                    cliente=cliente,
                    vendedor=request.user,
                    caixa=caixa,
                    repasse_logista=repasse_logista,
                    observacao=analise.observacao,
                    criado_por=request.user,
                    modificado_por=request.user,
                    criado_em=timezone.now(),
                    modificado_em=timezone.now(),
                )
                analise.venda = venda
                analise.save()

                ProdutoVenda.objects.create(
                    loja=analise.loja,
                    venda=venda,
                    produto=produto,
                    imei=imei.imei,
                    valor_unitario=valor_credfacil,
                    quantidade=1,
                    valor_desconto=0,
                )

                tipo_entrada = TipoPagamento.objects.get(nome__iexact="ENTRADA")
                tipo_credfacil = TipoPagamento.objects.get(nome__iexact="IPX")

                pagamento_entrada = Pagamento.objects.create(
                    loja=analise.loja,
                    venda=venda,
                    tipo_pagamento=tipo_entrada,
                    valor=valor_entrada,
                    parcelas=1,
                    data_primeira_parcela=timezone.now().date(),
                )

                data1 = calcular_data_primeira_parcela(analise.data_pagamento)
                pagamento_credfacil = Pagamento.objects.create(
                    loja=analise.loja,
                    venda=venda,
                    tipo_pagamento=tipo_credfacil,
                    valor=valor_credfacil,
                    parcelas=parcelas,
                    data_primeira_parcela=data1,
                    porcentagem_desconto=porcentagem_desconto,
                )

                criar_parcelas(pagamento_entrada, analise.loja)
                criar_parcelas(pagamento_credfacil, analise.loja)
        except Exception as exc:
            return Response({"detail": f"Erro ao processar a venda: {exc}"}, status=400)

        return Response(VendaSerializer(venda).data, status=201)


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
    permission_classes = [IsAuthenticated]
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


# Custom JWT Token View para incluir informações do usuário e lojas no login
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializers import CustomTokenObtainPairSerializer


class CustomTokenObtainPairView(TokenObtainPairView):
    """
    View customizada para login JWT que retorna tokens + informações do usuário e lojas.
    """
    serializer_class = CustomTokenObtainPairSerializer


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
            queryset = Produto.objects.filter(ativo=True)

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
        loja_id = self.request.session.get("loja_id")
        if not loja_id:
            raise ValidationError({"detail": "Loja nao encontrada na sessao."})
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
        loja_id = self.request.session.get("loja_id")
        if not loja_id:
            raise ValidationError({"detail": "Loja nao encontrada na sessao."})
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
    queryset = Marca.objects.all()
    serializer_class = MarcaSerializer
    permission_classes = [ProdutoPermission]

    def perform_create(self, serializer):
        loja_id = self.request.session.get("loja_id")
        if not loja_id:
            raise ValidationError({"detail": "Loja nao encontrada na sessao."})
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


def _build_formset_data(formset_cls, items, initial_forms=0):
    formset = formset_cls()
    prefix = formset.prefix

    from django.http import QueryDict

    data = QueryDict("", mutable=True)
    data[f"{prefix}-TOTAL_FORMS"] = str(len(items))
    data[f"{prefix}-INITIAL_FORMS"] = str(initial_forms)
    data[f"{prefix}-MIN_NUM_FORMS"] = "0"
    data[f"{prefix}-MAX_NUM_FORMS"] = "1000"

    for i, item in enumerate(items):
        for key, value in item.items():
            data[f"{prefix}-{i}-{key}"] = "" if value is None else str(value)

    return data


@extend_schema_view(
    list=extend_schema(tags=["Vendas"]),
    retrieve=extend_schema(tags=["Vendas"]),
    create=extend_schema(tags=["Vendas"]),
    update=extend_schema(tags=["Vendas"]),
    partial_update=extend_schema(tags=["Vendas"]),
    documentos=extend_schema(tags=["Vendas"]),
    edicao_especial=extend_schema(tags=["Vendas"]),
    trocar_produto=extend_schema(tags=["Vendas"]),
    cancelar=extend_schema(tags=["Vendas"]),
)
class VendaViewSet(viewsets.ModelViewSet):
    queryset = Venda.objects.all()
    serializer_class = VendaSerializer
    permission_classes = [VendaPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, required=False),
            OpenApiParameter("loja", OpenApiTypes.INT, required=False, description="ID da loja"),
            OpenApiParameter("cliente_nome", OpenApiTypes.STR, required=False),
            OpenApiParameter("vendas_canceladas", OpenApiTypes.STR, required=False),
            OpenApiParameter("vendas_trocadas", OpenApiTypes.STR, required=False),
        ],
        responses=VendaSerializer,
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        query = Venda.objects.all()
        data_filter = self.request.query_params.get("search")
        loja = self.request.query_params.get("loja") or self.request.query_params.get("loja_id")
        cliente_nome = self.request.query_params.get("cliente_nome")
        vendas_canceladas = self.request.query_params.get("vendas_canceladas")
        vendas_trocadas = self.request.query_params.get("vendas_trocadas")

        if data_filter:
            query = query.filter(data_venda=data_filter)
        if cliente_nome:
            query = query.filter(cliente__nome__icontains=cliente_nome)
        if vendas_canceladas:
            query = query.filter(is_deleted=True)
        if vendas_trocadas:
            query = query.filter(is_trocado=True)

        # Aplicar filtro de loja baseado em permissões
        if not self.request.user.has_perm("vendas.can_view_all_sales"):
            # Se loja foi especificada na query string, verificar se usuário tem acesso
            if loja:
                # Verificar se usuário tem acesso à loja solicitada
                lojas_usuario = self.request.user.lojas.values_list('id', flat=True)
                if int(loja) in lojas_usuario:
                    # Usuário tem acesso: usar filtro da query string
                    query = query.filter(loja__id=loja)
                else:
                    # Usuário não tem acesso: usar loja da sessão
                    loja_id = self.request.session.get("loja_id")
                    query = query.filter(loja_id=loja_id)
            else:
                # Sem filtro específico: usar loja da sessão
                loja_id = self.request.session.get("loja_id")
                query = query.filter(loja_id=loja_id)
        else:
            # Admin: respeitar filtro da query string se fornecido
            if loja:
                query = query.filter(loja__id=loja)

        return query.order_by("-criado_em")

    def _get_formset_payload(self, request, formset_cls, key, initial_forms=0):
        if key in request.data:
            items = request.data.get(key) or []
            return _build_formset_data(formset_cls, items, initial_forms=initial_forms)
        return request.data

    @extend_schema(
        request=VendaCreateUpdateSerializer,
        responses=VendaSerializer,
        examples=[
            OpenApiExample(
                "Exemplo venda",
                value={
                    "cliente": 1,
                    "vendedor": 2,
                    "observacao": "Venda via API",
                    "itens": [
                        {
                            "produto": 10,
                            "quantidade": 1,
                            "valor_unitario": "1200.00",
                            "valor_desconto": "0.00",
                            "imei": 5,
                        }
                    ],
                    "pagamentos": [
                        {
                            "tipo_pagamento": 3,
                            "valor": "1200.00",
                            "parcelas": 1,
                            "data_primeira_parcela": "2026-02-04",
                        }
                    ],
                },
            )
        ],
    )
    def create(self, request, *args, **kwargs):
        loja_id = request.session.get("loja_id")
        loja = Loja.objects.filter(id=loja_id).first()
        if not loja:
            return Response({"detail": "Loja nao encontrada na sessao."}, status=400)

        form = VendaForm(request.data, loja=loja_id, user=request.user)

        produto_data = self._get_formset_payload(request, ProdutoVendaFormSet, "itens", initial_forms=0)
        pagamento_data = self._get_formset_payload(request, FormaPagamentoFormSet, "pagamentos", initial_forms=0)

        produto_venda_formset = ProdutoVendaFormSet(
            produto_data, form_kwargs={"loja": loja_id}
        )
        pagamento_formset = FormaPagamentoFormSet(
            pagamento_data, form_kwargs={"loja": loja_id}
        )

        if not (produto_venda_formset.is_valid() and pagamento_formset.is_valid() and form.is_valid()):
            return Response(
                {
                    "detail": "Erros de validacao.",
                    "errors": {
                        "venda": form.errors,
                        "itens": produto_venda_formset.errors,
                        "pagamentos": pagamento_formset.errors,
                    },
                },
                status=400,
            )

        if not Caixa.caixa_aberto(timezone.localtime(timezone.now()).date(), loja):
            return Response({"detail": "Nao e possivel realizar vendas com a loja bloqueada."}, status=400)

        try:
            with transaction.atomic():
                form.instance.loja = loja
                form.instance.criado_por = request.user
                form.instance.modificado_por = request.user
                form.instance.caixa = (
                    Caixa.objects.filter(data_abertura=timezone.localtime(timezone.now()).date(), loja=loja)
                    .order_by("-criado_em")
                    .first()
                )
                form.instance.data_venda = timezone.localtime(timezone.now())
                venda = form.save()

                for produto_venda in produto_venda_formset.save(commit=False):
                    produto_venda.venda = venda
                    produto_venda.loja = loja
                    produto_venda.save()

                for pagamento in pagamento_formset.save(commit=False):
                    pagamento.venda = venda
                    pagamento.loja = loja
                    pagamento.save()
        except Exception as exc:
            return Response({"detail": f"Erro ao processar a venda: {exc}"}, status=400)

        return Response(VendaSerializer(venda).data, status=201)

    @extend_schema(
        request=VendaCreateUpdateSerializer,
        responses=VendaSerializer,
        examples=[
            OpenApiExample(
                "Exemplo update venda",
                value={
                    "cliente": 1,
                    "vendedor": 2,
                    "observacao": "Atualizacao",
                    "itens": [
                        {
                            "produto": 10,
                            "quantidade": 1,
                            "valor_unitario": "1200.00",
                            "valor_desconto": "0.00",
                            "imei": 5,
                        }
                    ],
                    "pagamentos": [
                        {
                            "tipo_pagamento": 3,
                            "valor": "1200.00",
                            "parcelas": 1,
                            "data_primeira_parcela": "2026-02-04",
                        }
                    ],
                },
            )
        ],
    )
    def update(self, request, *args, **kwargs):
        venda = self.get_object()
        loja_id = request.session.get("loja_id")

        try:
            loja = Loja.objects.get(id=loja_id)
        except Loja.DoesNotExist:
            return Response({"detail": "Loja nao encontrada."}, status=400)

        if not Caixa.caixa_aberto(timezone.localtime(timezone.now()).date(), loja):
            return Response({"detail": "Nao e possivel editar vendas com a loja bloqueada."}, status=400)

        form = VendaForm(request.data, instance=venda, loja=loja_id, user=request.user)

        produto_data = self._get_formset_payload(
            request, ProdutoVendaEditFormSet, "itens", initial_forms=venda.itens_venda.count()
        )
        pagamento_data = self._get_formset_payload(
            request, FormaPagamentoEditFormSet, "pagamentos", initial_forms=venda.pagamentos.count()
        )

        produto_venda_formset = ProdutoVendaEditFormSet(
            produto_data, instance=venda, form_kwargs={"loja": loja_id}
        )
        pagamento_formset = FormaPagamentoEditFormSet(
            pagamento_data, instance=venda, form_kwargs={"loja": loja_id}
        )

        if not (form.is_valid() and produto_venda_formset.is_valid() and pagamento_formset.is_valid()):
            return Response(
                {
                    "detail": "Erros de validacao.",
                    "errors": {
                        "venda": form.errors,
                        "itens": produto_venda_formset.errors,
                        "pagamentos": pagamento_formset.errors,
                    },
                },
                status=400,
            )

        try:
            with transaction.atomic():
                form.instance.loja = loja
                form.instance.modificado_por = request.user
                venda = form.save()

                for deletado in produto_venda_formset.deleted_objects:
                    deletado.delete()
                for produto_venda in produto_venda_formset.save(commit=False):
                    produto_venda.venda = venda
                    produto_venda.loja = loja
                    produto_venda.save()
                produto_venda_formset.save_m2m()

                for deletado in pagamento_formset.deleted_objects:
                    deletado.delete()
                for pagamento in pagamento_formset.save(commit=False):
                    pagamento.venda = venda
                    pagamento.loja = loja
                    pagamento.save()
                pagamento_formset.save_m2m()
        except Exception as exc:
            return Response({"detail": f"Erro ao processar a venda: {exc}"}, status=400)

        return Response(VendaSerializer(venda).data)

    @action(detail=True, methods=["post"], url_path="documentos")
    @extend_schema(request=VendaDocumentosSerializer, responses=VendaSerializer)
    def documentos(self, request, pk=None):
        venda = self.get_object()
        form = VendaDocumentosForm(request.data, request.FILES, instance=venda)
        if not form.is_valid():
            return Response({"detail": "Erros de validacao.", "errors": form.errors}, status=400)
        form.save()
        return Response(VendaSerializer(venda).data)

    @action(detail=True, methods=["post"], url_path="edicao-especial")
    @extend_schema(
        request=VendaEdicaoEspecialInputSerializer,
        responses=VendaSerializer,
        examples=[
            OpenApiExample(
                "Exemplo edicao especial",
                value={
                    "itens": [
                        {
                            "produto": 10,
                            "quantidade": 1,
                            "valor_unitario": "1200.00",
                            "valor_desconto": "0.00",
                            "imei": 5,
                        }
                    ],
                    "pagamentos": [
                        {
                            "tipo_pagamento": 3,
                            "valor": "1200.00",
                            "parcelas": 1,
                            "data_primeira_parcela": "2026-02-04",
                        }
                    ],
                },
            )
        ],
    )
    def edicao_especial(self, request, pk=None):
        venda = self.get_object()
        loja = venda.loja
        if not loja:
            return Response({"detail": "Loja nao encontrada na venda."}, status=400)

        if not Caixa.caixa_aberto(timezone.localtime(timezone.now()).date(), loja):
            return Response({"detail": "Nao e possivel editar vendas com a loja bloqueada."}, status=400)

        form = VendaEdicaoEspecialForm(request.data, instance=venda)

        produto_data = self._get_formset_payload(
            request, ProdutoVendaEdicaoEspecialFormSet, "itens", initial_forms=venda.itens_venda.count()
        )
        pagamento_data = self._get_formset_payload(
            request, FormaPagamentoEdicaoEspecialFormSet, "pagamentos", initial_forms=venda.pagamentos.count()
        )

        produto_venda_formset = ProdutoVendaEdicaoEspecialFormSet(
            produto_data, instance=venda, form_kwargs={"loja": loja.id}
        )
        pagamento_formset = FormaPagamentoEdicaoEspecialFormSet(pagamento_data, instance=venda)

        if not (form.is_valid() and produto_venda_formset.is_valid() and pagamento_formset.is_valid()):
            return Response(
                {
                    "detail": "Erros de validacao.",
                    "errors": {
                        "itens": produto_venda_formset.errors,
                        "pagamentos": pagamento_formset.errors,
                    },
                },
                status=400,
            )

        try:
            with transaction.atomic():
                form.instance.loja = loja
                form.instance.modificado_por = request.user
                venda = form.save()

                for produto_venda in produto_venda_formset.save(commit=False):
                    produto_venda.venda = venda
                    produto_venda.loja = loja
                    produto_venda.save()
                produto_venda_formset.save_m2m()

                produto_venda = venda.itens_venda.first()
                produto_base = produto_venda.produto if produto_venda else None
                quantidade_base = produto_venda.quantidade if produto_venda else 0

                entrada_base = None
                totais_parcelamento = {}
                if produto_base and produto_base.valor:
                    entrada_base = produto_base.entrada_cliente * quantidade_base
                    marca = produto_base.marca
                    parcelamentos_marca = {
                        p.qtd_vezes: p.porcentagem_juros
                        for p in Parcelamento.objects.filter(marca=marca)
                    }
                    valor_financiado_base = (produto_base.valor - produto_base.entrada_cliente) * quantidade_base
                    for qtd, juros in parcelamentos_marca.items():
                        totais_parcelamento[qtd] = valor_financiado_base + (valor_financiado_base * juros / 100)

                for pagamento in pagamento_formset.save(commit=False):
                    pagamento.venda = venda
                    pagamento.loja = loja
                    if pagamento.tipo_pagamento and pagamento.tipo_pagamento.nome.upper() == "ENTRADA":
                        if entrada_base is not None:
                            pagamento.valor = entrada_base
                    else:
                        try:
                            parcelas = int(pagamento.parcelas) if pagamento.parcelas else None
                        except (TypeError, ValueError):
                            parcelas = None
                        total = totais_parcelamento.get(parcelas)
                        if total is not None:
                            pagamento.valor = total
                    pagamento.save()
                pagamento_formset.save_m2m()
        except Exception as exc:
            return Response({"detail": f"Erro ao processar a venda: {exc}"}, status=400)

        return Response(VendaSerializer(venda).data)

    @action(detail=True, methods=["post"], url_path="trocar-produto")
    @extend_schema(request=VendaTrocaProdutoSerializer, responses={200: OpenApiTypes.OBJECT})
    def trocar_produto(self, request, pk=None):
        venda = self.get_object()
        produto_atual_id = request.data.get("produto_atual")
        novo_produto_id = request.data.get("novo_produto")
        imei_id = request.data.get("imei")
        motivo_troca = request.data.get("motivo")

        if not produto_atual_id or not novo_produto_id or not imei_id:
            return Response({"detail": "Todos os campos sao obrigatorios."}, status=400)

        try:
            imei_obj = EstoqueImei.objects.get(id=imei_id)
            imei = imei_obj.imei
        except EstoqueImei.DoesNotExist:
            return Response({"detail": "IMEI selecionado nao encontrado."}, status=400)

        try:
            produto_atual = ProdutoVenda.objects.get(id=produto_atual_id, venda=venda)
            novo_produto = Produto.objects.get(id=novo_produto_id)
        except Exception as exc:
            return Response({"detail": f"Erro ao trocar produto: {exc}"}, status=400)

        produto_antigo_nome = produto_atual.produto.nome
        produto_antigo_imei = produto_atual.imei

        produto_atual.produto = novo_produto
        produto_atual.imei = imei
        produto_atual.save(user=request.user)

        data_atual = timezone.localtime(timezone.now()).date().strftime("%d/%m/%Y")
        hora_atual = timezone.localtime(timezone.now()).time().strftime("%H:%M")

        venda.is_trocado = True
        venda.observacao = (venda.observacao or "") + (
            f"\n{data_atual} {hora_atual} | Troca de produto:\n"
            f"- Usuario: {request.user.username}\n"
            f"- De: {produto_antigo_nome} - {produto_antigo_imei}\n"
            f"- Para: {novo_produto.nome} - {imei}\n"
            f"- Motivo: {motivo_troca}"
        )
        venda.save(user=request.user)

        return Response({"detail": "Produto trocado com sucesso."})

    @action(detail=True, methods=["post"], url_path="cancelar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def cancelar(self, request, pk=None):
        venda = self.get_object()
        if venda.is_deleted:
            return Response({"detail": "Venda ja cancelada."}, status=400)

        if not Caixa.caixa_aberto(timezone.localtime(timezone.now()).date(), venda.loja):
            return Response({"detail": "Nao e possivel cancelar vendas com a loja bloqueada."}, status=400)

        venda.is_deleted = True
        venda.save(user=request.user)
        return Response({"detail": "Venda cancelada com sucesso."})

    @action(detail=True, methods=["get"], url_path="carne")
    @extend_schema(
        description="Retorna dados do carnê/promissória para geração de PDF no frontend",
        responses={200: OpenApiTypes.OBJECT},
    )
    def carne(self, request, pk=None):
        """
        Retorna dados estruturados do carnê ou promissória da venda.
        O frontend é responsável por gerar o PDF.
        
        Query params:
        - tipo (opcional): 'carne' ou 'promissoria' (padrão: 'carne')
        """
        venda = self.get_object()
        tipo = request.query_params.get('tipo', 'carne')
        
        # Buscar pagamento com carnê
        pagamento_carne = Pagamento.objects.filter(
            venda=venda,
            tipo_pagamento__carne=True
        ).first()
        
        if not pagamento_carne:
            return Response(
                {"detail": "Venda não possui pagamento em carnê ou promissória"},
                status=400
            )
        
        parcelas = pagamento_carne.parcelas_pagamento.all()
        cliente = venda.cliente
        loja = get_object_or_404(Loja, credfacil=True)
        
        parcelas_info = []
        for i, parcela in enumerate(parcelas):
            valor = f"{parcela.valor:.2f}"
            txid = f"{pagamento_carne.pk:04d}{i+1:02d}"
            descricao = f"{cliente.nome} - Parcela {i+1} de {len(parcelas)}"
            
            try:
                from vendas.views import gerar_qrcode_pix
                qr_base64 = gerar_qrcode_pix(
                    chave=loja.chave_pix,
                    valor=valor,
                    txid=txid,
                    nome_loja="CredFacil",
                    cidade_loja="Belem",
                    descricao=descricao
                )
            except:
                qr_base64 = None
            
            parcelas_info.append({
                'parcela': i + 1,
                'valor_parcela': valor,
                'data_vencimento': parcela.data_vencimento.strftime('%d/%m/%Y'),
                'qr_code_base64': qr_base64,
                'chave_pix': loja.chave_pix,
            })
        
        return Response({
            'venda_id': venda.id,
            'valor_total': str(venda.pagamentos_valor_total),
            'tipo_pagamento': 'Carnê' if tipo == 'carne' else 'Promissória',
            'quantidade_parcelas': len(parcelas),
            'nome_cliente': cliente.nome.title(),
            'endereco_cliente': cliente.endereco,
            'cpf': cliente.cpf,
            'data_atual': timezone.now().date().isoformat(),
            'parcelas_info': parcelas_info,
            'loja': {
                'nome': loja.nome,
                'telefone': loja.telefone,
                'cnpj': loja.cnpj,
            },
        })

    @action(detail=True, methods=["get"], url_path="contrato")
    @extend_schema(
        description="Retorna dados do contrato para geração de PDF no frontend",
        responses={200: OpenApiTypes.OBJECT},
    )
    def contrato(self, request, pk=None):
        """
        Retorna dados estruturados do contrato para a venda.
        O frontend é responsável por gerar o PDF.
        """
        venda = self.get_object()
        
        valor_total = venda.pagamentos_valor_total
        pagamento_carne = Pagamento.objects.filter(venda=venda, tipo_pagamento__carne=True).first()
        aparelho = venda.itens_venda.first()
        imei = aparelho.imei if aparelho else None
        
        # Tentar obter loja da sessão ou usar a loja da venda
        loja_id = request.session.get('loja_id') or venda.loja.id
        loja = get_object_or_404(Loja, id=loja_id)
        
        cliente = venda.cliente
        contrato = loja.contrato
        
        primeira_parcela = pagamento_carne.data_primeira_parcela if pagamento_carne else None
        parcelas = pagamento_carne.parcelas if pagamento_carne else 0
        parcelas_meses = []
        
        if primeira_parcela and parcelas:
            for i in range(parcelas):
                mes = primeira_parcela.month + i
                ano = primeira_parcela.year
                if mes > 12:
                    mes -= 12
                    ano += 1
                data_vencimento = primeira_parcela.replace(month=mes, year=ano)
                parcelas_meses.append(data_vencimento.strftime('%d/%m/%Y'))
        
        ultima_parcela = parcelas_meses[-1] if parcelas_meses else None
        
        return Response({
            'venda_id': venda.id,
            'valor_total': str(valor_total),
            'tipo_pagamento': 'Carnê' if pagamento_carne else 'À vista',
            'cliente': {
                'nome': cliente.nome,
                'cpf': cliente.cpf,
                'rg': cliente.rg,
                'endereco': cliente.endereco,
                'telefone': cliente.telefone,
            },
            'data_atual': timezone.now().date().isoformat(),
            'loja': {
                'nome': loja.nome,
                'cnpj': loja.cnpj,
                'endereco': loja.endereco,
                'contrato': contrato,
            },
            'aparelho': {
                'nome': aparelho.produto.nome if aparelho else None,
                'imei': imei,
            },
            'valor_parcela': str(pagamento_carne.valor_parcela) if pagamento_carne else None,
            'quantidade_parcelas': parcelas,
            'parcelas_meses': parcelas_meses,
            'primeira_parcela': primeira_parcela.strftime('%d/%m/%Y') if primeira_parcela else None,
            'ultima_parcela': ultima_parcela,
        })



class RepasseViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gerenciar repasses agendados.
    
    Endpoints disponíveis:
    - GET /api/repasses/ - Lista repasses (com filtros)
    - GET /api/repasses/agendados/ - Lista TODOS os repasses da loja (igual sistema web normal)
    - GET /api/repasses/{id}/ - Detalhe de um repasse
    - POST /api/repasses/ - Cria novo repasse
    - PUT /api/repasses/{id}/ - Atualiza repasse
    - PATCH /api/repasses/{id}/ - Atualiza parcialmente
    - DELETE /api/repasses/{id}/ - Deleta repasse
    """
    queryset = Repasse.objects.all()
    serializer_class = RepasseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    ordering_fields = ['data', 'valor', 'status']
    ordering = ['-data']
    
    def get_queryset(self):
        """
        Filtra repasses por:
        - loja: ID da loja
        - status: pendente, pago, cancelado (nenhum filtro de status por padrão)
        - data_inicio: data inicial (YYYY-MM-DD)
        - data_fim: data final (YYYY-MM-DD)
        
        Por padrão retorna TODOS os repasses sem filtrar por status.
        """
        queryset = Repasse.objects.all()
        user = self.request.user
        
        # Respeitar filtro de loja para não-admin
        loja_filter = self.request.query_params.get('loja')
        if loja_filter:
            try:
                loja_id = int(loja_filter)
                # Se não é admin, valida se tem acesso à loja
                if not user.is_superuser and not user.is_staff:
                    lojas_usuario = list(user.lojas.values_list('id', flat=True))
                    if loja_id in lojas_usuario:
                        queryset = queryset.filter(loja_id=loja_id)
                    elif 'loja_id' in self.request.session:
                        # Fallback para loja da sessão
                        queryset = queryset.filter(loja_id=self.request.session['loja_id'])
                else:
                    # Admin pode ver de qualquer loja
                    queryset = queryset.filter(loja_id=loja_id)
            except (ValueError, TypeError):
                pass
        elif 'loja_id' in self.request.session and not user.is_superuser:
            # Se não-admin e sem parâmetro loja, usa loja da sessão
            queryset = queryset.filter(loja_id=self.request.session['loja_id'])
        
        # Filtrar por status (opcional - sem padrão)
        status_filter = self.request.query_params.get('status')
        if status_filter in ['pendente', 'pago', 'cancelado']:
            queryset = queryset.filter(status=status_filter)
        
        # Filtrar por período
        data_inicio = self.request.query_params.get('data_inicio')
        if data_inicio:
            try:
                data_inicio_parsed = parse_date(data_inicio)
                if data_inicio_parsed:
                    queryset = queryset.filter(data__date__gte=data_inicio_parsed)
            except:
                pass
        
        data_fim = self.request.query_params.get('data_fim')
        if data_fim:
            try:
                data_fim_parsed = parse_date(data_fim)
                if data_fim_parsed:
                    queryset = queryset.filter(data__date__lte=data_fim_parsed)
            except:
                pass
        
        return queryset.order_by('-data')
    
    @action(detail=False, methods=['get'], url_path='agendados')
    @extend_schema(
        description='Retorna repasses calculados automaticamente baseado nos períodos de venda (dias 6, 16, 26)',
        responses={200: OpenApiTypes.OBJECT},
        parameters=[
            OpenApiParameter('loja', OpenApiTypes.INT, description='ID da loja (obrigatório para não-admin)'),
            OpenApiParameter('meses_atras', OpenApiTypes.INT, description='Quantos meses olhar para trás (padrão: 0, máximo: 6)'),
        ]
    )
    def agendados(self, request):
        """
        Retorna repasses CALCULADOS automaticamente pela loja.
        
        Baseado no método get_repasses_status do modelo Loja:
        - Calcula repasses nos dias 6, 16 e 26 de cada mês
        - Períodos de competência:
          * Dia 6: vendas de 26 do mês anterior até 05 do mês atual
          * Dia 16: vendas de 06 até 15 do mês atual
          * Dia 26: vendas de 16 até 25 do mês atual
        - Verifica se repasse foi registrado no banco (feito=True/False)
        - Calcula valor total baseado no repasse_logista de cada venda
        """
        user = request.user
        
        # Obter loja
        loja_id = request.query_params.get('loja')
        if loja_id:
            try:
                loja_id = int(loja_id)
                # Validar acesso para não-admin
                if not user.is_superuser and not user.is_staff:
                    lojas_usuario = list(user.lojas.values_list('id', flat=True))
                    if loja_id not in lojas_usuario:
                        return Response(
                            {'erro': 'Você não tem acesso a esta loja'},
                            status=status.HTTP_403_FORBIDDEN
                        )
                loja = Loja.objects.get(id=loja_id)
            except (ValueError, TypeError):
                return Response(
                    {'erro': 'ID da loja inválido'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Loja.DoesNotExist:
                return Response(
                    {'erro': 'Loja não encontrada'},
                    status=status.HTTP_404_NOT_FOUND
                )
        elif 'loja_id' in request.session:
            # Fallback para loja da sessão
            loja = Loja.objects.get(id=request.session['loja_id'])
        else:
            return Response(
                {'erro': 'Parâmetro loja é obrigatório'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obter quantos meses olhar para trás (padrão: 0)
        meses_atras = request.query_params.get('meses_atras', 0)
        try:
            meses_atras = int(meses_atras)
            meses_atras = max(0, min(meses_atras, 6))  # Limitar entre 0 e 6
        except (ValueError, TypeError):
            meses_atras = 0
        
        # Calcular repasses usando o método do modelo
        resultados, total_atrasados = loja.get_repasses_status(meses_atras=meses_atras)
        
        # Formatar resposta
        repasses_formatados = []
        for rep in resultados:
            repasses_formatados.append({
                'data': rep['data'].strftime('%Y-%m-%d'),
                'data_formatada': rep['data'].strftime('%d/%m/%Y'),
                'inicio_periodo': rep['inicio_periodo'].strftime('%Y-%m-%d'),
                'inicio_periodo_formatado': rep['inicio_periodo'].strftime('%d/%m/%Y'),
                'fim_periodo': rep['fim_periodo'].strftime('%Y-%m-%d'),
                'fim_periodo_formatado': rep['fim_periodo'].strftime('%d/%m/%Y'),
                'qtd_vendas': rep['qtd_vendas'],
                'valor_total_repasse': str(rep['valor_total_repasse']),
                'feito': rep['feito'],
                'atrasado': rep['data'] < date.today() and not rep['feito'],
            })
        
        return Response({
            'loja_id': loja.id,
            'loja_nome': loja.nome,
            'meses_consultados': meses_atras,
            'total_atrasados': total_atrasados,
            'repasses': repasses_formatados
        })
    
    @extend_schema(
        description='Lista repasses com filtros opcionais',
        parameters=[
            OpenApiParameter('loja', OpenApiTypes.INT, description='Filtrar por ID da loja'),
            OpenApiParameter('status', OpenApiTypes.STR, description='Filtrar por status: pendente, pago, cancelado'),
            OpenApiParameter('data_inicio', OpenApiTypes.DATE, description='Filtrar a partir desta data (YYYY-MM-DD)'),
            OpenApiParameter('data_fim', OpenApiTypes.DATE, description='Filtrar até esta data (YYYY-MM-DD)'),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
