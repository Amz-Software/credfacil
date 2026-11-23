"""Envio pela caixa de entrada: texto ou arquivo, digitando, reenvio, reação e textos prontos."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from crm.models import Mensagem, RespostaRapida
from crm.services import envio, organizacao

from ..apresentacao import mensagem_api
from ..base import CrmAPIView, obter_conversa
from ..permissoes import ACESSO
from ..serializers.entrada import ClienteQuerySerializer, EnviarSerializer, ReagirSerializer
from ..serializers.saida import MensagemSerializer, TextoProntoSerializer
from . import TAGS

PERM_VER_PAGAMENTO = 'vendas.view_pagamento'


def _mensagem(mensagem_id: int) -> Mensagem:
    return get_object_or_404(Mensagem.objects.select_related('conversa'), pk=mensagem_id)


def _responder_mensagem(mensagem: Mensagem, status: int = 200) -> Response:
    return Response(MensagemSerializer(mensagem_api(mensagem.pk)).data, status=status)


class EnviarView(CrmAPIView):
    permissoes = {'POST': ACESSO}
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=TAGS, summary='Enviar texto, ou arquivo (multipart) com legenda',
        description='Texto sai na hora (status ENVIADO ou ERRO com `erro`). Arquivo fica PENDENTE e sai em '
                    'segundo plano; acompanhe pelo evento `mensagem_status`/`conversa_atualizada`.',
        request={'multipart/form-data': EnviarSerializer, 'application/json': EnviarSerializer},
        responses={201: MensagemSerializer},
    )
    def post(self, request, pk: int):
        conversa = obter_conversa(pk)
        dados = self.validar(EnviarSerializer)
        arquivo = dados.get('arquivo')
        if arquivo is None:
            mensagem = envio.enviar_texto(conversa, dados['texto'], usuario=request.user,
                                          responde_a_id=dados.get('responde_a'))
        else:
            mensagem = envio.preparar_envio_midia(conversa, request.user, arquivo, legenda=dados['texto'],
                                                  voz=dados['voz'], responde_a_id=dados.get('responde_a'))
        return _responder_mensagem(mensagem, status=201)


class DigitandoView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Indicador "digitando..." (no máximo a cada 15 s; silencioso se bloqueado)',
                   request=None, responses={204: None})
    def post(self, request, pk: int):
        envio.digitando(obter_conversa(pk), request.user)
        return Response(status=204)


class ReenviarView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Reenviar mensagem com erro (abertura com erro sai de novo como template)',
                   request=None, responses=MensagemSerializer)
    def post(self, request, mensagem_id: int):
        mensagem = _mensagem(mensagem_id)
        envio.reenviar(mensagem, request.user)
        return _responder_mensagem(mensagem)


class ReagirView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Reagir a uma mensagem (últimos 30 dias; emoji vazio remove)',
                   request=ReagirSerializer, responses=MensagemSerializer)
    def post(self, request, mensagem_id: int):
        mensagem = _mensagem(mensagem_id)
        envio.reagir(mensagem, request.user, self.validar(ReagirSerializer)['emoji'])
        return _responder_mensagem(mensagem)


class ResumoPagamentosView(CrmAPIView):
    permissoes = {'GET': [*ACESSO, PERM_VER_PAGAMENTO]}

    @extend_schema(tags=TAGS, summary='Texto pronto com as parcelas em aberto do cliente (para revisar e enviar)',
                   parameters=[ClienteQuerySerializer], responses=TextoProntoSerializer)
    def get(self, request, pk: int):
        obter_conversa(pk)
        cliente_id = self.validar_query(ClienteQuerySerializer)['cliente']
        texto = organizacao.texto_resumo_pagamentos(request.user, cliente_id)
        return Response(TextoProntoSerializer({'texto': texto, 'avisos': []}).data)


class PreviaRespostaView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Resposta rápida com os marcadores preenchidos (sem valor entra em avisos)',
                   responses=TextoProntoSerializer)
    def get(self, request, pk: int, resposta_id: int):
        conversa = obter_conversa(pk)
        resposta = get_object_or_404(RespostaRapida, pk=resposta_id, ativo=True)
        return Response(TextoProntoSerializer(organizacao.previa_resposta(conversa, resposta, request.user)).data)
