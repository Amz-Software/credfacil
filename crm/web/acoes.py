"""Ações sobre a conversa: posse, situação, etiquetas, apelido, clientes e mensagens de abertura."""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from crm.models import Conversa
from crm.permissoes import pode_gerenciar
from crm.services import aberturas, avisos, conversas, organizacao
from crm.services.conversas import ConflitoCRM
from crm.web.base import acao, ler_inteiro, responder, url_conversa


def _conversa(pk: int) -> Conversa:
    return get_object_or_404(Conversa, pk=pk)


@acao
def assumir(request: HttpRequest, pk: int) -> HttpResponse:
    conversas.assumir(_conversa(pk), request.user)
    return responder(request, url_conversa(pk), 'Conversa assumida.')


@acao
def puxar(request: HttpRequest, pk: int) -> HttpResponse:
    conversas.puxar(_conversa(pk), request.user, ler_inteiro(request.POST.get('de'), 'de'))
    return responder(request, url_conversa(pk), 'Conversa puxada para você.')


@acao
def atribuir(request: HttpRequest, pk: int) -> HttpResponse:
    destino = get_object_or_404(get_user_model(), pk=ler_inteiro(request.POST.get('usuario'), 'usuario') or 0)
    conversas.atribuir(_conversa(pk), request.user, destino, pode_gerenciar(request.user))
    nome = destino.get_full_name() or destino.username
    return responder(request, url_conversa(pk), f'Conversa atribuída a {nome}.')


@acao
def devolver(request: HttpRequest, pk: int) -> HttpResponse:
    conversas.devolver(_conversa(pk), request.user, pode_gerenciar=pode_gerenciar(request.user))
    return responder(request, url_conversa(pk), 'Conversa devolvida ao atendimento automático.')


@acao
def situacao(request: HttpRequest, pk: int) -> HttpResponse:
    alvo = _conversa(pk)
    nova = request.POST.get('situacao')
    if nova not in Conversa.Situacao.values:
        raise ConflitoCRM('Situação inválida.')
    devolver_automatico = request.POST.get('devolver_automatico') == '1'
    if devolver_automatico and nova != Conversa.Situacao.RESOLVIDA:
        raise ConflitoCRM('Só é possível devolver ao automático ao resolver.')
    with transaction.atomic():  # se a devolução for recusada, a situação também não muda
        conversas.mudar_situacao(alvo, nova, request.user)
        if devolver_automatico:
            conversas.devolver(alvo, request.user, pode_gerenciar=pode_gerenciar(request.user))
        avisos.emitir(alvo, 'conversa_atualizada')
    return responder(request, url_conversa(pk), f'Conversa marcada como {Conversa.Situacao(nova).label.lower()}.')


@acao
def etiquetas(request: HttpRequest, pk: int) -> HttpResponse:
    ids = [ler_inteiro(valor, 'etiquetas') for valor in request.POST.getlist('etiquetas') if valor]
    organizacao.definir_etiquetas(_conversa(pk), ids)
    return responder(request, url_conversa(pk), 'Etiquetas atualizadas.')


@acao
def apelido(request: HttpRequest, pk: int) -> HttpResponse:
    organizacao.definir_apelido(_conversa(pk), request.POST.get('apelido', ''))
    return responder(request, url_conversa(pk), 'Apelido salvo.')


@acao
def vincular_cliente(request: HttpRequest, pk: int) -> HttpResponse:
    cliente_id = ler_inteiro(request.POST.get('cliente'), 'cliente')
    if not cliente_id:
        raise ConflitoCRM('Escolha um cliente.')
    organizacao.vincular_cliente(_conversa(pk), cliente_id, True, request.user)
    return responder(request, url_conversa(pk), 'Cliente vinculado à conversa.')


@acao
def desvincular_cliente(request: HttpRequest, pk: int) -> HttpResponse:
    cliente_id = ler_inteiro(request.POST.get('cliente'), 'cliente')
    if not cliente_id:
        raise ConflitoCRM('Escolha um cliente.')
    organizacao.vincular_cliente(_conversa(pk), cliente_id, False)
    return responder(request, url_conversa(pk), 'Cliente desvinculado.')


@acao
def abrir(request: HttpRequest, pk: int) -> HttpResponse:
    aberturas.enviar_abertura(_conversa(pk), request.user, request.POST.get('modelo', ''),
                              request.POST.get('nome', ''))
    return responder(request, url_conversa(pk), 'Mensagem de abertura enviada.')


@acao
def iniciar(request: HttpRequest) -> HttpResponse:
    nova = aberturas.iniciar_conversa(request.POST.get('telefone', ''), request.user,
                                      request.POST.get('modelo', ''), request.POST.get('nome', ''))
    destino = url_conversa(nova.pk)
    return responder(request, destino, 'Conversa iniciada.', {'redirecionar': destino})
