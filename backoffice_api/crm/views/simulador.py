"""Simulador de mensagens recebidas (`crm.gerenciar_crm`), só com o WhatsApp simulado (sem credenciais).

A conversa simulada é atendida pela caixa de entrada normal: depois de `receber/`, abra
`GET conversas/{conversa_id}/mensagens/` para ver a resposta automática.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from crm.models import Conversa
from crm.services import organizacao
from crm.services.conversas import ConflitoCRM

from ..apresentacao import mensagem_api
from ..base import CrmAPIView
from ..permissoes import GERENCIA
from ..serializers.configuracao import (
    SimuladorLeituraSerializer, SimuladorLerSerializer, SimuladorReceberSerializer, SimuladorRecebidaSerializer,
    SimuladorSerializer,
)
from ..servicos import simulado
from . import TAGS

CONVERSAS_RECENTES = 50
MENSAGEM_SO_SIMULADO = 'O simulador só funciona sem as credenciais da Meta.'


def _exigir_simulado() -> None:
    if not simulado():
        raise ConflitoCRM(MENSAGEM_SO_SIMULADO)


class SimuladorView(CrmAPIView):
    permissoes = {'GET': GERENCIA}

    @extend_schema(tags=TAGS, summary='Simulador: disponível? e conversas recentes', responses=SimuladorSerializer)
    def get(self, request):
        recentes = Conversa.objects.order_by('-ultima_mensagem_em', '-id')[:CONVERSAS_RECENTES]
        return Response(SimuladorSerializer({'disponivel': simulado(), 'conversas': recentes}).data)


class SimuladorReceberView(CrmAPIView):
    permissoes = {'POST': GERENCIA}

    @extend_schema(tags=TAGS, summary='Receber mensagem como se fosse o cliente (409 com credenciais da Meta)',
                   request=SimuladorReceberSerializer, responses={201: SimuladorRecebidaSerializer})
    def post(self, request):
        _exigir_simulado()
        dados = self.validar(SimuladorReceberSerializer)
        mensagem = organizacao.simular_recebida(dados['telefone'], dados['nome'], dados['texto'])
        return Response(SimuladorRecebidaSerializer({
            'conversa_id': mensagem.conversa_id if mensagem else None,
            'mensagem': mensagem_api(mensagem.pk) if mensagem else None,
        }).data, status=201)


class SimuladorLerView(CrmAPIView):
    permissoes = {'POST': GERENCIA}

    @extend_schema(tags=TAGS, summary='Cliente leu as mensagens enviadas (tiques azuis simulados)',
                   request=SimuladorLerSerializer, responses=SimuladorLeituraSerializer)
    def post(self, request):
        _exigir_simulado()
        conversa = get_object_or_404(Conversa, pk=self.validar(SimuladorLerSerializer)['conversa'])
        return Response(SimuladorLeituraSerializer({'alteradas': organizacao.simular_leitura(conversa)}).data)
