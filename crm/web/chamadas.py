"""Rotas JSON das ligações pelo WhatsApp (usadas por static/js/crm/chamadas.js).

O navegador negocia o áudio (WebRTC) e manda só o SDP; o servidor fala com a Meta.
Erro de regra vira 409 com `detail` (e `motivo`, ex.: SEM_PERMISSAO) pronto para a tela.
"""
import json

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from crm.models import Chamada, ConfiguracaoCRM, Conversa
from crm.services import chamadas
from crm.services.conversas import ConflitoCRM
from crm.services.expediente import DOMINGO, SABADO
from crm.telefone import formatar_telefone
from crm.web.base import acesso_crm, gerencia_crm, responder, responder_erro
from crm.whatsapp import ErroWhatsApp
from crm.whatsapp_chamadas import obter_chamadas

DIAS_META = ('MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY')
FUSO = 'America/Belem'


def _dados(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


def _erro(erro: ConflitoCRM) -> JsonResponse:
    return JsonResponse({'detail': erro.detail, 'motivo': erro.motivo}, status=409)


def _json(chamada: Chamada) -> dict:
    conversa = chamada.conversa
    return {
        'id': chamada.pk, 'status': chamada.status, 'status_display': chamada.get_status_display(),
        'direcao': chamada.direcao, 'conversa_id': conversa.pk, 'nome': conversa.nome_exibicao,
        'telefone': formatar_telefone(conversa.telefone), 'usuario_id': chamada.usuario_id,
        'sdp_oferta': chamada.sdp_oferta if chamada.status == Chamada.Status.TOCANDO else '',
        'sdp_resposta': chamada.sdp_resposta if chamada.direcao == Chamada.Direcao.SAIDA else '',
        'atendida_em': chamada.atendida_em.isoformat() if chamada.atendida_em else None,
    }


@require_GET
@acesso_crm
def detalhe(request: HttpRequest, chamada_id: int) -> JsonResponse:
    return JsonResponse(_json(get_object_or_404(Chamada.objects.select_related('conversa'), pk=chamada_id)))


@require_GET
@acesso_crm
def tocando(request: HttpRequest) -> JsonResponse:
    """Ligações tocando agora (a página abre depois do aviso em tempo real)."""
    ativas = Chamada.objects.filter(status=Chamada.Status.TOCANDO).select_related('conversa')[:5]
    return JsonResponse({'chamadas': [_json(c) for c in ativas]})


@require_POST
@acesso_crm
def atender(request: HttpRequest, chamada_id: int) -> JsonResponse:
    chamada = get_object_or_404(Chamada.objects.select_related('conversa'), pk=chamada_id)
    try:
        chamada = chamadas.atender(chamada, request.user, _dados(request).get('sdp', ''))
    except ConflitoCRM as erro:
        return _erro(erro)
    return JsonResponse(_json(chamada))


@require_POST
@acesso_crm
def encerrar(request: HttpRequest, chamada_id: int) -> JsonResponse:
    chamada = get_object_or_404(Chamada.objects.select_related('conversa'), pk=chamada_id)
    try:
        chamada = chamadas.encerrar(chamada, request.user)
    except ConflitoCRM as erro:
        return _erro(erro)
    return JsonResponse(_json(chamada))


@require_POST
@acesso_crm
def ligar(request: HttpRequest, pk: int) -> JsonResponse:
    conversa = get_object_or_404(Conversa, pk=pk)
    try:
        chamada = chamadas.ligar(conversa, request.user, _dados(request).get('sdp', ''))
    except ConflitoCRM as erro:
        return _erro(erro)
    return JsonResponse(_json(chamada))


@require_POST
@acesso_crm
def pedir_permissao(request: HttpRequest, pk: int) -> JsonResponse:
    try:
        chamadas.pedir_permissao(get_object_or_404(Conversa, pk=pk), request.user)
    except ConflitoCRM as erro:
        return _erro(erro)
    return JsonResponse({'ok': True, 'mensagem': 'Pedido de permissão enviado ao cliente.'})


def _horario_meta(config: ConfiguracaoCRM) -> dict:
    """Horário de atendimento da Configuração no formato da Meta (fora dele o botão de ligar some)."""
    dias = []
    for indice, dia in enumerate(DIAS_META):
        fim = config.hora_fechamento_sabado if indice == SABADO else config.hora_fechamento
        if indice == DOMINGO or fim is None:
            continue
        dias.append({'day_of_week': dia, 'open_time': f'{config.hora_abertura:%H%M}', 'close_time': f'{fim:%H%M}'})
    return {'status': 'ENABLED', 'timezone_id': FUSO, 'weekly_operating_hours': dias}


@require_POST
@gerencia_crm
def ativar_no_numero(request: HttpRequest) -> HttpResponse:
    """Liga a Calling API no número: botão de ligar no horário da empresa e permissão de retorno."""
    config = ConfiguracaoCRM.obter()
    destino = reverse('crm:configuracao')
    try:
        obter_chamadas().configurar({
            'status': 'ENABLED', 'call_icon_visibility': 'DEFAULT', 'callback_permission_status': 'ENABLED',
            'call_hours': _horario_meta(config),
        })
    except ErroWhatsApp as erro:
        return responder_erro(request, destino, f'A Meta não ativou as ligações: {erro.mensagem}')
    ConfiguracaoCRM.objects.filter(pk=config.pk).update(chamadas_ativas=True)
    return responder(request, destino, 'Ligações ativadas no número do WhatsApp.')
