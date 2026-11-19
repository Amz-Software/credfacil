"""Pré-análise rápida."""
import logging

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.permissions import PreAnaliseRapidaPermission
from api.serializers import PreAnaliseRapidaInputSerializer, PreAnaliseRapidaSerializer
from vendas.models import Cliente, PreAnaliseRapida

from .solicitacoes_regras import _resolver_loja_solicitacao


logger = logging.getLogger(__name__)


class PreAnaliseRapidaViewSet(viewsets.ModelViewSet):
    """Pré-análise rápida: vendedor cria (React), analista pré-aprova/reprova
    (backoffice Django), vendedor/gerente veem o resultado e finalizam a proposta."""
    permission_classes = [PreAnaliseRapidaPermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return PreAnaliseRapidaInputSerializer
        return PreAnaliseRapidaSerializer

    def _lojas_usuario_ids(self, request):
        lojas_ids = set(request.user.lojas.values_list("id", flat=True))
        if getattr(request.user, "loja_id", None):
            lojas_ids.add(request.user.loja_id)
        return lojas_ids

    def get_queryset(self):
        request = self.request
        qs = PreAnaliseRapida.objects.select_related(
            "loja", "criado_por", "analisado_por", "cliente_gerado"
        ).order_by("-criado_em")

        # Escopo: quem vê todas as análises vê tudo; senão, apenas das suas lojas
        if not (
            request.user.is_superuser
            or request.user.has_perm("vendas.view_all_analise_credito")
        ):
            qs = qs.filter(loja_id__in=self._lojas_usuario_ids(request))

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # ?finalizada=0 lista somente as que ainda não viraram proposta
        finalizada = request.query_params.get("finalizada")
        if finalizada == "0":
            qs = qs.filter(cliente_gerado__isnull=True)
        elif finalizada == "1":
            qs = qs.filter(cliente_gerado__isnull=False)

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(Q(nome_completo__icontains=search) | Q(cpf__icontains=search))

        return qs

    def create(self, request, *args, **kwargs):
        loja, erro = _resolver_loja_solicitacao(request, request.data)
        if erro:
            return Response({"detail": erro}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(loja=loja, criado_por=request.user, modificado_por=request.user)
        saida = PreAnaliseRapidaSerializer(instance, context={"request": request})
        return Response(saida.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def aprovar(self, request, pk=None):
        instance = self.get_object()
        instance.aprovar(user=request.user)
        return Response(PreAnaliseRapidaSerializer(instance, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def reprovar(self, request, pk=None):
        instance = self.get_object()
        motivo = request.data.get("observacao") or request.data.get("motivo")
        instance.reprovar(user=request.user, motivo=motivo)
        return Response(PreAnaliseRapidaSerializer(instance, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="marcar-finalizada")
    def marcar_finalizada(self, request, pk=None):
        instance = self.get_object()
        cliente_id = request.data.get("cliente")
        if cliente_id:
            cliente = Cliente.objects.filter(id=cliente_id).first()
            if cliente:
                instance.cliente_gerado = cliente
                instance.save(user=request.user)
                # A consulta Serasa anexada pelo analista na análise rápida já
                # nasce preenchida nos comprovantes da proposta gerada.
                instance.aplicar_consulta_serasa(cliente, user=request.user)
                # A marcação de segunda compra feita na análise rápida é
                # levada automaticamente para a solicitação gerada.
                instance.aplicar_segunda_compra(cliente, user=request.user)
        return Response(PreAnaliseRapidaSerializer(instance, context={"request": request}).data)
