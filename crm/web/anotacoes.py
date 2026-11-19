"""Notas internas, lembrete e mensagens programadas da conversa."""
from django.contrib.auth import get_user_model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from crm.models import Conversa, MensagemProgramada, Nota
from crm.services import organizacao
from crm.web.base import acao, ler_datahora, ler_inteiro, responder, url_conversa


@acao
def criar_nota(request: HttpRequest, pk: int) -> HttpResponse:
    organizacao.criar_nota(get_object_or_404(Conversa, pk=pk), request.user, request.POST.get('texto', ''))
    return responder(request, url_conversa(pk), 'Nota adicionada.')


@acao
def apagar_nota(request: HttpRequest, pk: int, nota_id: int) -> HttpResponse:
    nota = get_object_or_404(Nota, pk=nota_id, conversa_id=pk, apagada_em__isnull=True)
    organizacao.apagar_nota(nota, request.user)
    return responder(request, url_conversa(pk), 'Nota apagada.')


@acao
def definir_lembrete(request: HttpRequest, pk: int) -> HttpResponse:
    para_id = ler_inteiro(request.POST.get('para'), 'para')
    para = get_object_or_404(get_user_model(), pk=para_id) if para_id else None
    organizacao.definir_lembrete(get_object_or_404(Conversa, pk=pk), request.user,
                                 ler_datahora(request.POST.get('lembrete_em')), request.POST.get('texto', ''), para)
    return responder(request, url_conversa(pk), 'Lembrete salvo.')


@acao
def concluir_lembrete(request: HttpRequest, pk: int) -> HttpResponse:
    organizacao.concluir_lembrete(get_object_or_404(Conversa, pk=pk))
    return responder(request, url_conversa(pk), 'Lembrete concluído.')


@acao
def programar(request: HttpRequest, pk: int) -> HttpResponse:
    organizacao.programar(get_object_or_404(Conversa, pk=pk), request.user, request.POST.get('texto', ''),
                          ler_datahora(request.POST.get('enviar_em')))
    return responder(request, url_conversa(pk), 'Mensagem programada.')


@acao
def cancelar_programada(request: HttpRequest, programada_id: int) -> HttpResponse:
    programada = get_object_or_404(MensagemProgramada, pk=programada_id)
    organizacao.cancelar_programada(programada, request.user)
    return responder(request, url_conversa(programada.conversa_id), 'Mensagem programada cancelada.')
