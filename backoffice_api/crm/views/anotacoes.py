"""Notas internas, lembrete e mensagens programadas da conversa."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from crm.apresentacao import nota_dict, programada_dict
from crm.models import MensagemProgramada, Nota
from crm.services import organizacao

from ..base import CrmAPIView, obter_conversa
from ..permissoes import ACESSO
from ..serializers.entrada import LembreteEntradaSerializer, NotaEntradaSerializer, ProgramarSerializer
from ..serializers.saida import NotaSerializer, ProgramadaSerializer
from . import TAGS
from .acoes import AcaoConversaView, documentar


class NotasView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Nova nota interna (o cliente não vê)', request=NotaEntradaSerializer,
                   responses={201: NotaSerializer})
    def post(self, request, pk: int):
        conversa = obter_conversa(pk)
        nota = organizacao.criar_nota(conversa, request.user, self.validar(NotaEntradaSerializer)['texto'])
        nota = Nota.objects.select_related('usuario').get(pk=nota.pk)
        return Response(NotaSerializer(nota_dict(nota, request.user)).data, status=201)


class ApagarNotaView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Apagar nota (só quem escreveu; automáticas não)', request=None,
                   responses={204: None})
    def post(self, request, pk: int, nota_id: int):
        nota = get_object_or_404(Nota.objects.select_related('conversa'), pk=nota_id, conversa_id=pk,
                                 apagada_em__isnull=True)
        organizacao.apagar_nota(nota, request.user)
        return Response(status=204)


@documentar('Definir lembrete (data futura; padrão: para quem cria)', LembreteEntradaSerializer)
class LembreteView(AcaoConversaView):
    entrada = LembreteEntradaSerializer

    def executar(self, conversa, dados):
        organizacao.definir_lembrete(conversa, self.request.user, dados['lembrete_em'], dados['texto'],
                                     dados.get('para'))


@documentar('Concluir o lembrete')
class ConcluirLembreteView(AcaoConversaView):
    def executar(self, conversa, dados):
        organizacao.concluir_lembrete(conversa)


def _programada(programada_id: int) -> MensagemProgramada:
    return MensagemProgramada.objects.select_related('criado_por').get(pk=programada_id)


class ProgramadasView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Programar mensagem (5 min a 30 dias; exige poder responder agora)',
                   request=ProgramarSerializer, responses={201: ProgramadaSerializer})
    def post(self, request, pk: int):
        conversa = obter_conversa(pk)
        dados = self.validar(ProgramarSerializer)
        programada = organizacao.programar(conversa, request.user, dados['texto'], dados['enviar_em'])
        return Response(ProgramadaSerializer(programada_dict(_programada(programada.pk))).data, status=201)


class CancelarProgramadaView(CrmAPIView):
    permissoes = {'POST': ACESSO}

    @extend_schema(tags=TAGS, summary='Cancelar mensagem programada (409 se já saiu)', request=None,
                   responses=ProgramadaSerializer)
    def post(self, request, programada_id: int):
        programada = get_object_or_404(MensagemProgramada.objects.select_related('conversa'), pk=programada_id)
        organizacao.cancelar_programada(programada, request.user)
        return Response(ProgramadaSerializer(programada_dict(_programada(programada.pk))).data)
