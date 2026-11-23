"""Caixa de entrada: lista com filtros e contadores, conversa, leitura, mensagens e nova conversa."""
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from crm.apresentacao import anotar_lista
from crm.models import Mensagem
from crm.services import aberturas
from crm.web.filtros import Filtros, contadores, filtrar_conversas

from ..apresentacao import detalhe, estado, itens_lista, pagina_mensagens
from ..base import CrmAPIView, obter_conversa
from ..permissoes import ACESSO
from ..serializers.entrada import CursorMensagensSerializer, FiltrosConversasSerializer, IniciarSerializer
from ..serializers.saida import (
    ConversaDetalheSerializer, ConversaEstadoSerializer, ConversaItemSerializer, ListaConversasSerializer,
    PaginaMensagensSerializer,
)
from ..servicos import marcar_lida
from . import TAGS


def _filtros(params: dict) -> Filtros:
    return Filtros(
        fila=params['fila'], situacao=params.get('situacao') or '', etiqueta=params.get('etiqueta'),
        nao_lidas=params['nao_lidas'], busca=(params.get('busca') or '').strip(), ordem=params['ordenar'],
    )


class ConversasView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Lista de conversas (filas, filtros e contadores)',
                   parameters=[FiltrosConversasSerializer], responses=ListaConversasSerializer)
    def get(self, request):
        filtros = _filtros(self.validar_query(FiltrosConversasSerializer))
        qs = anotar_lista(filtrar_conversas(filtros, request.user))
        resposta = self.paginar_convertendo(qs, itens_lista, ConversaItemSerializer)
        resposta.data['contadores'] = contadores(request.user)
        return resposta


class ConversaView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Conversa: cabeçalho, trava de resposta, painel do cliente, notas e programadas',
                   description='Não marca como lida: use POST .../ler/.', responses=ConversaDetalheSerializer)
    def get(self, request, pk: int):
        return Response(ConversaDetalheSerializer(detalhe(obter_conversa(pk), request.user)).data)


class LerView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Marcar como lida (zera não lidas e manda o recibo de leitura)',
                   request=None, responses=ConversaEstadoSerializer)
    def post(self, request, pk: int):
        marcar_lida(obter_conversa(pk))
        return Response(ConversaEstadoSerializer(estado(pk, request.user)).data)


class MensagensView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Mensagens da conversa, da mais recente para trás (cursor)',
                   parameters=[CursorMensagensSerializer], responses=PaginaMensagensSerializer)
    def get(self, request, pk: int):
        conversa = obter_conversa(pk)
        params = self.validar_query(CursorMensagensSerializer)
        antes = None
        if params.get('antes'):
            antes = Mensagem.objects.filter(conversa=conversa, pk=params['antes']).first()
            if antes is None:
                raise ValidationError({'antes': ['Mensagem não encontrada nesta conversa.']})
        return Response(PaginaMensagensSerializer(pagina_mensagens(conversa, antes, params['limite'])).data)


class IniciarView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Nova conversa com uma mensagem de abertura aprovada',
                   request=IniciarSerializer, responses={201: ConversaEstadoSerializer})
    def post(self, request):
        dados = self.validar(IniciarSerializer)
        nova = aberturas.iniciar_conversa(dados['telefone'], request.user, dados['modelo'], dados['nome'])
        return Response(ConversaEstadoSerializer(estado(nova.pk, request.user)).data, status=201)
