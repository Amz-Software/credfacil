"""ViewSet de vendas (criação, edição, documentos, troca, carnê, contrato e recibo)."""
import logging
import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiExample,
    OpenApiParameter,
    OpenApiTypes,
)
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.permissions import VendaPermission
from api.serializers import (
    VendaCreateUpdateSerializer,
    VendaDocumentosSerializer,
    VendaEdicaoEspecialInputSerializer,
    VendaSerializer,
    VendaTrocaProdutoSerializer,
)
from estoque.models import EstoqueImei
from produtos.models import Produto
from vendas.forms import (
    FormaPagamentoEdicaoEspecialFormSet,
    FormaPagamentoEditFormSet,
    FormaPagamentoFormSet,
    ProdutoVendaEdicaoEspecialFormSet,
    ProdutoVendaEditFormSet,
    ProdutoVendaFormSet,
    VendaEdicaoEspecialForm,
    VendaForm,
)
from vendas.models import Caixa, Loja, Pagamento, ProdutoVenda, Venda

from .comum import ERRO_INESPERADO_VENDA
from .publico import _montar_payload_contrato


logger = logging.getLogger(__name__)


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
    gerar_link_contrato=extend_schema(tags=["Vendas"]),
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
        else:
            query = query.filter(is_deleted=False)
        if vendas_trocadas:
            query = query.filter(is_trocado=True)

        # Aplicar filtro de loja baseado em permissões
        if not self.request.user.has_perm("vendas.can_view_all_sales"):
            # Lojas vinculadas ao usuário (JWT-friendly)
            lojas_usuario = set(self.request.user.lojas.values_list('id', flat=True))

            # Inclui loja principal, quando existir
            if hasattr(self.request.user, "loja_id") and self.request.user.loja_id:
                lojas_usuario.add(self.request.user.loja_id)

            # Se loja veio na query e o usuário tem acesso, usa filtro explícito
            if loja:
                try:
                    loja_id_query = int(loja)
                except (TypeError, ValueError):
                    loja_id_query = None

                if loja_id_query and loja_id_query in lojas_usuario:
                    query = query.filter(loja_id=loja_id_query)
                elif lojas_usuario:
                    # Fallback seguro: restringe às lojas do usuário
                    query = query.filter(loja_id__in=lojas_usuario)
                else:
                    # Último fallback para contexto web legado
                    loja_id_sessao = self.request.session.get("loja_id")
                    query = query.filter(loja_id=loja_id_sessao)
            else:
                # Sem loja na query: restringe às lojas do usuário, sem depender de sessão
                if lojas_usuario:
                    query = query.filter(loja_id__in=lojas_usuario)
                else:
                    loja_id_sessao = self.request.session.get("loja_id")
                    query = query.filter(loja_id=loja_id_sessao)
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
        except Exception:
            logger.exception("Erro ao processar a venda pela API")
            return Response({"detail": ERRO_INESPERADO_VENDA}, status=400)

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
        except Exception:
            logger.exception("Erro ao processar a venda pela API")
            return Response({"detail": ERRO_INESPERADO_VENDA}, status=400)

        return Response(VendaSerializer(venda).data)

    @action(detail=True, methods=["post"], url_path="documentos")
    @extend_schema(request=VendaDocumentosSerializer, responses=VendaSerializer)
    def documentos(self, request, pk=None):
        venda = self.get_object()

        # API upload parcial: aceita qualquer subconjunto dos arquivos.
        campos_arquivos = ("documento_assinado", "foto_cliente", "imagem_imei")
        updated_fields = []

        for campo in campos_arquivos:
            arquivo = request.FILES.get(campo)
            if arquivo:
                setattr(venda, campo, arquivo)
                updated_fields.append(campo)

        if not updated_fields:
            return Response(
                {
                    "detail": "Erros de validacao.",
                    "errors": {
                        "files": [
                            "Envie ao menos um arquivo: documento_assinado, foto_cliente ou imagem_imei."
                        ]
                    },
                },
                status=400,
            )

        venda.save(update_fields=updated_fields)
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

                # Edição especial NÃO altera valores monetários: o valor do produto
                # (valor_unitario/valor_desconto) e o valor do pagamento são preservados
                # exatamente como já estão gravados. Os formulários só expõem campos
                # não monetários (produto, imei e parcelas), então qualquer "valor"
                # enviado é ignorado e nada é recalculado a partir do produto.
                for pagamento in pagamento_formset.save(commit=False):
                    pagamento.venda = venda
                    pagamento.loja = loja
                    pagamento.save()
                pagamento_formset.save_m2m()
        except Exception:
            logger.exception("Erro ao processar a venda pela API")
            return Response({"detail": ERRO_INESPERADO_VENDA}, status=400)

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
        except (ProdutoVenda.DoesNotExist, Produto.DoesNotExist, ValueError):
            return Response({"detail": "Produto da venda ou novo produto não encontrado."}, status=400)

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

        with transaction.atomic():
            venda.is_deleted = True
            venda.save(user=request.user)

            imeis = [pv.imei for pv in venda.itens_venda.all() if pv.imei]
            if imeis:
                EstoqueImei.objects.filter(
                    imei__in=imeis, produto__in=[pv.produto for pv in venda.itens_venda.all()]
                ).update(vendido=False)
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
        
        parcelas = pagamento_carne.parcelas_pagamento.order_by('numero_parcela')
        cliente = venda.cliente
        loja = get_object_or_404(Loja, credfacil=True)

        # O carnê SEMPRE reflete o pagamento IPX: valor da parcela = pagamento.valor / parcelas
        # e a quantidade vem do próprio pagamento. Nunca usa o valor do produto.
        quantidade_parcelas = pagamento_carne.parcelas or parcelas.count()
        valor_parcela_pagamento = (
            pagamento_carne.valor / pagamento_carne.parcelas
            if pagamento_carne.parcelas else pagamento_carne.valor
        )

        parcelas_info = []
        for i, parcela in enumerate(parcelas):
            valor = f"{valor_parcela_pagamento:.2f}"
            txid = f"{pagamento_carne.pk:04d}{i+1:02d}"
            descricao = f"{cliente.nome} - Parcela {i+1} de {quantidade_parcelas}"
            
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
            'quantidade_parcelas': quantidade_parcelas,
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

    @action(detail=True, methods=["post"], url_path="gerar-link-contrato")
    @extend_schema(
        description="Gera (ou reutiliza) link publico do contrato da venda.",
        responses={200: OpenApiTypes.OBJECT},
    )
    def gerar_link_contrato(self, request, pk=None):
        venda = self.get_object()

        if not venda.contrato_publico_uuid:
            venda.contrato_publico_uuid = uuid.uuid4()

        if venda.status_contrato != Venda.CONTRATO_STATUS_ASSINADO:
            venda.status_contrato = Venda.CONTRATO_STATUS_AGUARDANDO_ASSINATURA

        venda.save(update_fields=["contrato_publico_uuid", "status_contrato"])

        url = request.build_absolute_uri(
            reverse("api-contrato-publico", kwargs={"token": venda.contrato_publico_uuid})
        )
        return Response({"url": url})

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

        # Tentar obter loja da sessão ou usar a loja da venda
        loja_id = request.session.get('loja_id') or venda.loja.id
        loja = get_object_or_404(Loja, id=loja_id)

        return Response(_montar_payload_contrato(venda, loja))

    @action(detail=True, methods=["get"], url_path="recibo")
    @extend_schema(
        description="Retorna dados da nota de venda (recibo) para geração de PDF no frontend",
        responses={200: OpenApiTypes.OBJECT},
    )
    def recibo(self, request, pk=None):
        """
        Retorna dados detalhados para o recibo de venda.
        O frontend é responsável por gerar o PDF usando esses dados.
        """
        venda = self.get_object()
        cliente = venda.cliente
        loja = venda.loja
        
        itens = []
        for item in venda.itens_venda.all():
            itens.append({
                'codigo': item.produto.codigo if item.produto else '',
                'nome': item.produto.nome if item.produto else 'Item sem nome',
                'imei': item.imei or '',
                'quantidade': item.quantidade,
                'valor_unitario': str(item.valor_unitario),
                'valor_desconto': str(item.valor_desconto),
                'valor_total': str(item.calcular_valor_total())
            })
            
        pagamentos = []
        for p in venda.pagamentos.all():
            pagamentos.append({
                'tipo_pagamento': p.tipo_pagamento.nome if p.tipo_pagamento else 'N/A',
                'valor': str(p.valor),
                'parcelas': p.parcelas,
                'data_primeira_parcela': p.data_primeira_parcela.strftime('%d/%m/%Y') if p.data_primeira_parcela else None
            })
            
        return Response({
            'venda_id': venda.id,
            'data_venda': venda.data_venda.strftime('%d/%m/%Y %H:%M'),
            'vendedor': venda.vendedor.get_full_name() or venda.vendedor.username,
            'loja': {
                'nome': loja.nome,
                'endereco': loja.endereco,
                'cnpj': loja.cnpj,
                'logo': request.build_absolute_uri(loja.logo_loja.url) if loja.logo_loja else None,
                'mensagem_garantia': loja.mensagem_garantia,
            },
            'cliente': {
                'nome': cliente.nome,
                'telefone': cliente.telefone,
                'telefone_secundario': cliente.telefone_secundario,
                'cpf': cliente.cpf,
                'email': cliente.email,
                'endereco': cliente.endereco,
                'cep': cliente.cep,
                'cidade': cliente.cidade,
                'uf': getattr(cliente, 'uf', '') or '',
            },
            'itens': itens,
            'pagamentos': pagamentos,
            'valor_total': str(venda.calcular_valor_total()),
        })
