"""Base das views do CRM na API do backoffice.

Os serviços do CRM (`crm/services/*`) levantam `ConflitoCRM` (regra violada, hoje 409 nas
telas) e `ErroMidia` (anexo inválido). Aqui eles entram no contrato de erro do backoffice:

- `ConflitoCRM` → 409 `conflito`, com `erro.motivo` quando o serviço informa
  (`OUTRO_DONO`, `JANELA_FECHADA`, `NAO_ASSUMIDA`);
- `ErroMidia` → 400 `validacao`, com a mensagem em `erro.campos.arquivo`.
"""
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from backoffice_api.nucleo.erros import CONFLITO, VALIDACAO, corpo_erro, tratar_excecao
from backoffice_api.nucleo.views import BackofficeAPIView
from crm.models import Conversa
from crm.services.conversas import ConflitoCRM
from crm.services.midias import ErroMidia

STATUS_CONFLITO = 409
STATUS_VALIDACAO = 400
CAMPO_ARQUIVO = 'arquivo'


def tratar_excecao_crm(exc, context) -> Response:
    if isinstance(exc, ConflitoCRM):
        corpo = corpo_erro(CONFLITO, exc.detail)
        if exc.motivo:
            corpo['erro']['motivo'] = exc.motivo
        return Response(corpo, status=STATUS_CONFLITO)
    if isinstance(exc, ErroMidia):
        mensagem = str(exc)
        return Response(corpo_erro(VALIDACAO, mensagem, {CAMPO_ARQUIVO: [mensagem]}), status=STATUS_VALIDACAO)
    return tratar_excecao(exc, context)


class CrmAPIView(BackofficeAPIView):
    """APIView do CRM: contrato de erro com os erros do CRM e validação da entrada por serializer."""

    def get_exception_handler(self):
        return tratar_excecao_crm

    def check_permissions(self, request):
        # Método sem handler é 405 (e não 403 de "ação não declarada"): GET numa ação nunca muta nada.
        if not hasattr(self, request.method.lower()):
            raise MethodNotAllowed(request.method)
        super().check_permissions(request)

    def validar(self, serializer_class, dados=None, parcial: bool = False) -> dict:
        """Valida `dados` (padrão: corpo da requisição); erro vira 400 com `campos`."""
        entrada = serializer_class(data=self.request.data if dados is None else dados, partial=parcial,
                                   context={'request': self.request})
        entrada.is_valid(raise_exception=True)
        return entrada.validated_data

    def validar_query(self, serializer_class) -> dict:
        return self.validar(serializer_class, self.request.query_params)

    def paginar_convertendo(self, queryset, conversor, serializer_class) -> Response:
        """Paginação padrão quando cada item passa por `conversor` (lista → dicionários) antes do serializer."""
        paginador = self.pagination_class()
        pagina = paginador.paginate_queryset(queryset, self.request, view=self)
        return paginador.get_paginated_response(serializer_class(conversor(pagina), many=True).data)


def obter_conversa(pk: int) -> Conversa:
    return get_object_or_404(Conversa, pk=pk)
