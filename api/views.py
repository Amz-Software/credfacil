from datetime import date

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

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
)
from vendas.models import AnaliseCreditoCliente, Cliente, Loja, Venda
from accounts.models import User

from .pagination import SolicitacaoPagination
from .permissions import LojaPermission, SolicitacaoCreditoPermission
from .serializers import (
    ClienteSolicitacaoSerializer,
    LojaListSerializer,
    LojaSerializer,
    RepasseSerializer,
    VendaSerializer,
)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


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
    def reprovar(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito
        analise.reprovar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        return Response({"detail": "Analise de credito reprovada com sucesso."})

    @action(detail=True, methods=["post"], url_path="cancelar")
    def cancelar(self, request, pk=None):
        cliente = Cliente.objects.get(pk=pk)
        analise = cliente.analise_credito
        analise.cancelar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        return Response({"detail": "Analise de credito cancelada com sucesso."})
