"""Envio pela caixa de entrada: texto, mídia, reenvio, reação, digitando e textos prontos."""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404

from crm.models import Conversa, Mensagem, RespostaRapida
from crm.services import envio, midias, organizacao
from crm.services.conversas import ConflitoCRM
from crm.web.base import acao, ler_inteiro, responder, url_conversa


@acao
def enviar(request: HttpRequest, pk: int) -> HttpResponse:
    """Texto, ou arquivo com o texto como legenda (o mesmo formulário do compositor)."""
    conversa = get_object_or_404(Conversa, pk=pk)
    texto = request.POST.get('texto', '')
    responde_a_id = ler_inteiro(request.POST.get('responde_a'), 'responde_a')
    arquivo = request.FILES.get('arquivo')
    if arquivo is None:
        envio.enviar_texto(conversa, texto, usuario=request.user, responde_a_id=responde_a_id)
        return responder(request, url_conversa(pk))
    if arquivo.size > midias.LIMITE_ENVIO:
        raise ConflitoCRM('O arquivo passa de 25 MB.')
    envio.preparar_envio_midia(conversa, request.user, arquivo, legenda=texto, voz=request.POST.get('voz') == '1',
                               responde_a_id=responde_a_id)
    return responder(request, url_conversa(pk))


@acao
def reenviar(request: HttpRequest, mensagem_id: int) -> HttpResponse:
    mensagem = get_object_or_404(Mensagem, pk=mensagem_id)
    envio.reenviar(mensagem, request.user)
    return responder(request, url_conversa(mensagem.conversa_id), 'Mensagem reenviada.')


@acao
def reagir(request: HttpRequest, mensagem_id: int) -> HttpResponse:
    mensagem = get_object_or_404(Mensagem, pk=mensagem_id)
    envio.reagir(mensagem, request.user, request.POST.get('emoji', ''))
    return responder(request, url_conversa(mensagem.conversa_id))


@acao
def digitando(request: HttpRequest, pk: int) -> HttpResponse:
    envio.digitando(get_object_or_404(Conversa, pk=pk), request.user)
    return responder(request, url_conversa(pk))


@acao
def resumo_pagamentos(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Conversa, pk=pk)
    cliente_id = ler_inteiro(request.POST.get('cliente'), 'cliente')
    if not cliente_id:
        raise ConflitoCRM('Escolha um cliente.')
    texto = organizacao.texto_resumo_pagamentos(request.user, cliente_id)
    return responder(request, url_conversa(pk), dados={'texto': texto})


@acao
def previa_resposta(request: HttpRequest, pk: int, resposta_id: int) -> HttpResponse:
    conversa = get_object_or_404(Conversa, pk=pk)
    resposta = get_object_or_404(RespostaRapida, pk=resposta_id, ativo=True)
    return responder(request, url_conversa(pk), dados=organizacao.previa_resposta(conversa, resposta, request.user))
