"""Etapas da análise pela API: Serasa, IMEI/telefone, app, iCloud, status e geração da venda."""
import logging

from django.utils import timezone
from drf_spectacular.utils import (
    extend_schema,
    inline_serializer,
    OpenApiExample,
    OpenApiParameter,
    OpenApiTypes,
)
from rest_framework import serializers as drf_serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response

from api.serializers import (
    ClienteSolicitacaoSerializer,
    ConsultaSerasaAcessoSerializer,
    InformarImeiAnaliseInputSerializer,
    SolicitacaoImeiTelefoneInputSerializer,
    VendaSerializer,
)
from vendas.forms import AnaliseCreditoClienteImeiForm, ClienteTelefoneForm
from vendas.models import Cliente, Loja
from vendas.services import analise as servico_analise, ErroDeNegocio
from vendas.services.venda import gerar_venda_da_analise

from .comum import _resposta_de_erro
from .solicitacoes_regras import _validar_marca_produto_solicitacao, gerar_qrcode_instalacao


logger = logging.getLogger(__name__)


class EtapasDaAnaliseMixin:
    # Sem docstring: o drf-spectacular usaria o texto como descrição das operações.
    # Usa os auxiliares definidos em SolicitacaoCreditoViewSet.


    @action(detail=True, methods=["post"], url_path="log-consulta-serasa")
    @extend_schema(
        request=inline_serializer(
            name="LogConsultaSerasaInput",
            fields={"tipo": drf_serializers.ChoiceField(choices=["serasa", "serasa_2"])},
        ),
        responses=ConsultaSerasaAcessoSerializer,
        tags=["Solicitacoes"],
    )
    def log_consulta_serasa(self, request, pk=None):
        from vendas.models import ConsultaSerasaAcesso

        tipo = request.data.get("tipo")
        if tipo not in {"serasa", "serasa_2"}:
            return Response(
                {"detail": "Campo 'tipo' deve ser 'serasa' ou 'serasa_2'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cliente = self._cliente_no_escopo(request, pk)

        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:512]

        acesso = ConsultaSerasaAcesso.objects.create(
            cliente=cliente,
            usuario=request.user if request.user.is_authenticated else None,
            tipo=tipo,
            ip_address=ip,
            user_agent=user_agent,
        )
        return Response(
            ConsultaSerasaAcessoSerializer(acesso).data,
            status=status.HTTP_201_CREATED,
        )


    @action(detail=True, methods=["post"], url_path="imei-telefone")
    @extend_schema(
        request=SolicitacaoImeiTelefoneInputSerializer,
        responses=ClienteSolicitacaoSerializer,
        examples=[
            OpenApiExample(
                "Exemplo imei",
                value={
                    "telefone": "11999999999",
                    "telefone_secundario": "11988888888",
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
        cliente = self._cliente_no_escopo(request, pk)
        user = request.user

        cliente_data = request.data.dict() if hasattr(request.data, "dict") else dict(request.data)
        cliente_data.setdefault("telefone_secundario", cliente.telefone_secundario)
        form_cliente = ClienteTelefoneForm(cliente_data, instance=cliente, user=user)
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
        cliente = self._cliente_no_escopo(request, pk)
        try:
            analise = servico_analise.atualizar_status_aplicativo(
                cliente.analise_credito, request.data.get("status_app"),
            )
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response(
            {"detail": f"Status do aplicativo atualizado para {analise.get_status_aplicativo_display()}."}
        )


    @action(detail=True, methods=["post"], url_path="instalar-app")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def instalar_app(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        analise_credito = cliente.analise_credito
        servico_analise.marcar_instalacao_pendente(analise_credito)
        return Response({"detail": "Status alterado para Confirmação Pendente."})


    @action(detail=True, methods=["get"], url_path="gerar-qrcode-instalacao")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def gerar_qrcode_instalacao_endpoint(self, request, pk=None):
        """
        Gera QR code de instalação do app.
        
        Retorna um JSON contendo:
        - qr_code_base64: Imagem PNG do QR code em base64
        - codigo_instalacao: Token alfanumérico de 16 caracteres
        - dados_qr: Dados codificados no QR code
        
        Parâmetros opcionais:
        - loja: ID da loja (obrigatório se não houver sessão web)
        - device_id: ID do dispositivo (opcional)
        """
        cliente = self._cliente_no_escopo(request, pk)
        loja_id = cliente.loja_id
        
        # Gerar QR code + código de instalação
        device_id = request.query_params.get("device_id", "")
        qr_base64, codigo_instalacao = gerar_qrcode_instalacao(
            cliente_id=cliente.id,
            loja_id=loja_id,
            device_id=device_id
        )
        
        return Response({
            "detail": "QR code gerado com sucesso.",
            "qr_code_base64": qr_base64,
            "codigo_instalacao": codigo_instalacao,
            "dados_qr": {
                "cliente_id": cliente.id,
                "loja_id": loja_id,
                "timestamp": timezone.now().isoformat(),
                "device_id": device_id,
                "codigo_instalacao": codigo_instalacao
            }
        })


    def _confirmar_leitura_qrcode(self, request, cliente):
        analise_credito = cliente.analise_credito
        # Últimos 4 dígitos do IMEI informados pelo vendedor (referência para o analista).
        digitos = servico_analise.digitos_imei(request.data.get("imei_ultimos_digitos"))
        servico_analise.confirmar_instalacao_vendedor(analise_credito, request.user, digitos=digitos)
        return Response({"detail": "Leitura do QR code confirmada. Aguardando analista informar IMEI."})


    @action(detail=True, methods=["post"], url_path="confirmar-app")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def confirmar_app(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        return self._confirmar_leitura_qrcode(request, cliente)


    @action(detail=True, methods=["post"], url_path="confirmar-leitura-qrcode")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def confirmar_leitura_qrcode(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        return self._confirmar_leitura_qrcode(request, cliente)


    @action(detail=True, methods=["post"], url_path="configurar-icloud")
    @extend_schema(
        request=inline_serializer("ConfigurarIcloudInput", fields={"imei_ultimos_digitos": drf_serializers.CharField()}),
        responses={200: OpenApiTypes.OBJECT},
    )
    def configurar_icloud(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        analise = cliente.analise_credito
        try:
            servico_analise.configurar_icloud(analise, request.user, request.data.get("imei_ultimos_digitos"))
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response({"detail": f"Configuração iCloud confirmada para {cliente.nome}."})


    @action(detail=True, methods=["post"], url_path="analista-confirm-icloud")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def analista_confirm_icloud(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        try:
            servico_analise.exigir_analista(request.user, "Apenas analistas podem confirmar o iCloud.")
            self._exigir_loja_do_usuario(request, cliente)
            servico_analise.confirmar_icloud_analista(cliente.analise_credito, request.user)
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response({"detail": f"Configuração iCloud confirmada pelo analista para {cliente.nome}."})


    @action(detail=True, methods=["post"], url_path="analista-confirmar-instalacao")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def analista_confirm_installed(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        try:
            servico_analise.exigir_analista(request.user, "Apenas analistas podem confirmar a instalação.")
            self._exigir_loja_do_usuario(request, cliente)
            servico_analise.confirmar_instalacao_analista(
                cliente.analise_credito, request.user, target_url=f"/app/solicitacoes/{cliente.pk}",
            )
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response({"detail": f"Instalação do app confirmada para {cliente.nome}."})


    @action(detail=True, methods=["post"], url_path="informar-imei-analise")
    @extend_schema(request=InformarImeiAnaliseInputSerializer, responses={200: OpenApiTypes.OBJECT})
    def informar_imei_analise(self, request, pk=None):
        cliente = self._cliente_no_escopo(
            request, pk, Cliente.objects.select_related("analise_credito__produto"),
        )
        imei_informado = (request.data.get("imei_informado") or "").strip()
        try:
            servico_analise.exigir_analista(request.user, "Apenas analistas podem informar IMEI.")
            analise = servico_analise.analise_do_cliente(cliente)
            servico_analise.informar_imei(analise, request.user, imei_informado, analise.loja)
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response(
            {
                "detail": "IMEI informado com sucesso. Venda liberada para geração.",
                "cliente_id": cliente.id,
                "analise_id": analise.id,
                "imei_informado": imei_informado,
            }
        )


    @action(detail=True, methods=["post"], url_path="aprovar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def aprovar(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        servico_analise.aprovar_analise(cliente.analise_credito, request.user)
        return Response({"detail": "Análise de crédito aprovada com sucesso."})


    @action(detail=True, methods=["post"], url_path="reprovar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def reprovar(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        servico_analise.reprovar_analise(cliente.analise_credito, request.user)
        return Response({"detail": "Análise de crédito reprovada com sucesso."})


    @action(detail=True, methods=["post"], url_path="cancelar")
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def cancelar(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        servico_analise.cancelar_analise(cliente.analise_credito, request.user, desfazer_venda=True)
        return Response({"detail": "Análise de crédito cancelada com sucesso."})


    @action(detail=True, methods=["post"], url_path="gerar-venda")
    @extend_schema(request=None, responses=VendaSerializer)
    def gerar_venda(self, request, pk=None):
        cliente = self._cliente_no_escopo(request, pk)
        if not Loja.objects.filter(credfacil=True).exists():
            return Response({"detail": "Loja CredFacil não encontrada."}, status=400)

        try:
            venda = gerar_venda_da_analise(cliente, request.user, bloquear_imei_de_venda_cancelada=False)
        except ErroDeNegocio as erro:
            return _resposta_de_erro(erro)
        return Response(VendaSerializer(venda).data, status=201)
