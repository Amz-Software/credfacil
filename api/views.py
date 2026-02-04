from datetime import date
import re
import calendar

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
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
from produtos.models import Produto
from estoque.models import EstoqueImei
from accounts.models import User

from .pagination import SolicitacaoPagination
from .permissions import LojaPermission, SolicitacaoCreditoPermission, ProdutoPermission, VendaPermission
from .serializers import (
    ClienteSolicitacaoSerializer,
    LojaListSerializer,
    LojaSerializer,
    ProdutoSerializer,
    VendaSerializer,
    RepasseSerializer,
    SolicitacaoCreditoInputSerializer,
    SolicitacaoImeiTelefoneInputSerializer,
    VendaCreateUpdateSerializer,
    VendaDocumentosSerializer,
    VendaEdicaoEspecialInputSerializer,
    VendaTrocaProdutoSerializer,
)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


def calcular_data_primeira_parcela(data_pagamento_str):
    hoje = timezone.now().date()
    dia_escolhido = int(data_pagamento_str)
    max_dias = 40
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

        repasses_qs = Repasse.objects.filter(loja=loja).select_related("criado_por")
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
        }

        return Response(payload)

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

        if loja_filter:
            qs = qs.filter(loja_id=loja_filter)

        if data_inicio and data_fim:
            qs = qs.filter(analise_credito__data_analise__range=[data_inicio, data_fim]).distinct()
        elif data_inicio:
            qs = qs.filter(analise_credito__data_analise__gte=data_inicio).distinct()
        elif data_fim:
            qs = qs.filter(analise_credito__data_analise__lte=data_fim).distinct()

        if vendas_nao_finalizadas:
            qs = qs.filter(analise_credito__venda__isnull=True).distinct()

        if not request.user.has_perm("vendas.view_all_analise_credito"):
            loja_id = request.session.get("loja_id")
            if loja_id:
                qs = qs.filter(loja_id=loja_id)
            else:
                qs = qs.none()

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
        cliente = Cliente.objects.select_related(
            "loja", "contato_adicional", "informacao_pessoal", "comprovantes", "analise_credito"
        ).get(pk=pk)
        if not request.user.has_perm("vendas.view_all_analise_credito"):
            loja_id = request.session.get("loja_id")
            if cliente.loja_id != loja_id:
                return Response({"detail": "Acao nao autorizada para esta loja."}, status=403)
        data = ClienteSolicitacaoSerializer(cliente).data
        return Response(data)

    @transaction.atomic
    @extend_schema(
        request=SolicitacaoCreditoInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo",
                value={
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
                venda = Venda.objects.create(
                    loja=analise.loja,
                    cliente=cliente,
                    vendedor=request.user,
                    caixa=caixa,
                    repasse_logista=produto.valor_repasse_logista,
                    observacao=analise.observacao,
                    criado_por=request.user,
                    modificado_por=request.user,
                    criado_em=timezone.now(),
                    modificado_em=timezone.now(),
                )
                analise.venda = venda
                analise.save()

                porcentagem_desconto = 0
                if analise.numero_parcelas == "4":
                    valor_credfacil = produto.valor_4_vezes
                    parcelas = 4
                    porcentagem_desconto = credfacil.porcentagem_desconto_4
                elif analise.numero_parcelas == "6":
                    valor_credfacil = produto.valor_6_vezes
                    parcelas = 6
                    porcentagem_desconto = credfacil.porcentagem_desconto_6
                elif analise.numero_parcelas == "8":
                    valor_credfacil = produto.valor_8_vezes
                    parcelas = 8
                    porcentagem_desconto = credfacil.porcentagem_desconto_8
                elif analise.numero_parcelas == "10":
                    valor_credfacil = produto.valor_10_vezes
                    parcelas = 10
                    porcentagem_desconto = credfacil.porcentagem_desconto_10
                elif analise.numero_parcelas == "12":
                    valor_credfacil = produto.valor_12_vezes
                    parcelas = 12
                else:
                    valor_credfacil = produto.valor_14_vezes
                    parcelas = 14

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
                    valor=produto.entrada_cliente,
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
        if search:
            queryset = queryset.filter(nome__icontains=search)

        return queryset.order_by("nome")

    @extend_schema(
        parameters=[OpenApiParameter("search", OpenApiTypes.STR, required=False)],
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
            OpenApiParameter("loja_id", OpenApiTypes.INT, required=False),
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
        loja = self.request.query_params.get("loja_id")
        cliente_nome = self.request.query_params.get("cliente_nome")
        vendas_canceladas = self.request.query_params.get("vendas_canceladas")
        vendas_trocadas = self.request.query_params.get("vendas_trocadas")

        if loja:
            query = query.filter(loja__id=loja)
        if data_filter:
            query = query.filter(data_venda=data_filter)
        if cliente_nome:
            query = query.filter(cliente__nome__icontains=cliente_nome)
        if vendas_canceladas:
            query = query.filter(is_deleted=True)
        if vendas_trocadas:
            query = query.filter(is_trocado=True)

        if not self.request.user.has_perm("vendas.can_view_all_sales"):
            loja_id = self.request.session.get("loja_id")
            query = query.filter(loja_id=loja_id)

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
                if produto_base:
                    entrada_base = produto_base.entrada_cliente * quantidade_base
                    totais_parcelamento = {
                        4: produto_base.valor_4_vezes * quantidade_base,
                        6: produto_base.valor_6_vezes * quantidade_base,
                        8: produto_base.valor_8_vezes * quantidade_base,
                        10: produto_base.valor_10_vezes * quantidade_base,
                        12: produto_base.valor_12_vezes * quantidade_base,
                        14: produto_base.valor_14_vezes * quantidade_base,
                    }

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
