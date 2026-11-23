"""Notificações do usuário logado.

Módulo de referência da API do backoffice: views finas sobre `BackofficeAPIView`,
permissões declaradas (aqui vazias: cada um só vê as próprias notificações),
mutações sempre por POST e filtros/serialização em arquivos próprios.
"""
from django.shortcuts import get_object_or_404
from notifications.base.models import is_soft_delete
from rest_framework.response import Response

from ..nucleo.views import BackofficeAPIView
from .filtros import filtrar_notificacoes
from .serializers import MarcarSelecionadasSerializer, NotificacaoSerializer


def notificacoes_do_usuario(request):
    """Ponto único de escopo: só as notificações do próprio usuário (nunca por id solto)."""
    queryset = request.user.notifications.all()
    if is_soft_delete():
        queryset = queryset.filter(deleted=False)
    return queryset


class NotificacaoListaView(BackofficeAPIView):
    """GET /notificacoes/?lida=&busca=&ordenar=&page=&page_size="""

    permissoes = {'GET': []}

    def get(self, request):
        queryset = filtrar_notificacoes(notificacoes_do_usuario(request), request.query_params)
        return self.paginar(queryset, NotificacaoSerializer)


class NotificacaoNaoLidasView(BackofficeAPIView):
    """GET /notificacoes/nao-lidas/ → {"nao_lidas": n} (contador do sino)."""

    permissoes = {'GET': []}

    def get(self, request):
        return Response({'nao_lidas': notificacoes_do_usuario(request).filter(unread=True).count()})


class NotificacaoMarcarLidaView(BackofficeAPIView):
    """POST /notificacoes/<id>/marcar-lida/ → a notificação atualizada (404 se não for sua)."""

    permissoes = {'POST': []}

    def post(self, request, pk: int):
        notificacao = get_object_or_404(notificacoes_do_usuario(request), pk=pk)
        notificacao.mark_as_read()
        return Response(NotificacaoSerializer(notificacao).data)


class NotificacaoMarcarSelecionadasView(BackofficeAPIView):
    """POST /notificacoes/marcar-lidas/ {"ids": [..]} → {"atualizadas": n}. Ids de outros usuários são ignorados."""

    permissoes = {'POST': []}

    def post(self, request):
        entrada = MarcarSelecionadasSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        atualizadas = (
            notificacoes_do_usuario(request)
            .filter(unread=True, pk__in=entrada.validated_data['ids'])
            .update(unread=False)
        )
        return Response({'atualizadas': atualizadas})


class NotificacaoMarcarTodasView(BackofficeAPIView):
    """POST /notificacoes/marcar-todas-lidas/ → {"atualizadas": n}."""

    permissoes = {'POST': []}

    def post(self, request):
        atualizadas = notificacoes_do_usuario(request).filter(unread=True).update(unread=False)
        return Response({'atualizadas': atualizadas})
