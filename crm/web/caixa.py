"""Caixa de entrada do CRM: página, trechos recarregados pelo JS, busca de cliente e mídia."""
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from crm import tarefas
from crm.apresentacao import (
    LIMITE_MENSAGENS_DETALHE, anotar_lista, base_mensagens, conversa_detalhe, conversa_estado, conversa_resumo,
    mensagens_dicts,
)
from crm.services.conversas import bloqueio_de
from crm.models import Conversa, Etiqueta, RespostaRapida
from crm.permissoes import pode_gerenciar, usuarios_com_acesso
from crm.services import aberturas, envio, organizacao
from crm.web.base import acesso_crm, inteiro_ou_none
from crm.web.filtros import FILAS, ORDENS, Filtros, contadores, filtrar_conversas
from crm.whatsapp import obter_provider

LIMITE_LISTA = 100
PARTES = {
    'cabecalho': 'crm/parciais/cabecalho.html',
    'mensagens': 'crm/parciais/mensagens.html',
    'compositor': 'crm/parciais/compositor.html',
    'painel': 'crm/parciais/painel.html',
}


def _contexto_lista(request: HttpRequest, filtros: Filtros, conversa_atual: int | None = None) -> dict:
    qs = filtrar_conversas(filtros, request.user)
    agora = timezone.now()
    conversas = [conversa_resumo(c, agora) for c in anotar_lista(qs)[:LIMITE_LISTA]]
    return {
        'filtros': filtros, 'filas': FILAS, 'ordens': ORDENS, 'contadores': contadores(request.user),
        'conversas': conversas, 'total_lista': qs.count() if len(conversas) == LIMITE_LISTA else len(conversas),
        'situacoes': Conversa.Situacao.choices, 'etiquetas_filtro': Etiqueta.objects.filter(ativo=True),
        'conversa_atual': conversa_atual,
    }


def _marcar_lida(conversa: Conversa) -> None:
    if conversa.nao_lidas:
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0)
        tarefas.agendar(envio.enviar_recibo_leitura, conversa.pk)


def _contexto_base(usuario) -> dict:
    """O que os trechos da conversa usam além dos dados dela (consultas preguiçosas)."""
    return {
        'pode_gerenciar': pode_gerenciar(usuario),
        'respostas_rapidas': RespostaRapida.objects.filter(ativo=True),
        'atendentes': usuarios_com_acesso().order_by('first_name', 'username'),
        'etiquetas_todas': Etiqueta.objects.filter(ativo=True),
        've_pagamentos': usuario.has_perm('vendas.view_pagamento'),
        've_clientes': usuario.has_perm('vendas.view_cliente'),
    }


def _contexto_da_pagina() -> dict:
    """Modal "Nova conversa" e aviso de modo simulado (página inteira, com ou sem conversa)."""
    return {'aberturas': aberturas.disponiveis(), 'simulado': bool(getattr(obter_provider(), 'simulado', False))}


def _contexto_pagina(conversa: Conversa, usuario) -> dict:
    return {
        **_contexto_base(usuario),
        **_contexto_da_pagina(),
        'conversa': conversa_detalhe(conversa, usuario),
        'painel': organizacao.painel(conversa, usuario),
    }


def _contexto_parte(conversa: Conversa, usuario, nome: str) -> dict:
    contexto = _contexto_base(usuario)
    if nome in ('cabecalho', 'compositor'):
        contexto['conversa'] = conversa_estado(conversa, usuario)
    elif nome == 'mensagens':
        contexto['conversa'] = conversa_detalhe(conversa, usuario, anotacoes=False)
    else:
        contexto['conversa'] = conversa_detalhe(conversa, usuario, mensagens=False)
        contexto['painel'] = organizacao.painel(conversa, usuario)
    return contexto


@require_GET
@acesso_crm
def caixa(request: HttpRequest) -> HttpResponse:
    filtros = Filtros.do_request(request.GET)
    return render(request, 'crm/caixa.html', {**_contexto_lista(request, filtros), **_contexto_da_pagina(),
                                              'conversa': None})


@require_GET
@acesso_crm
def conversa(request: HttpRequest, pk: int) -> HttpResponse:
    alvo = get_object_or_404(Conversa, pk=pk)
    _marcar_lida(alvo)
    filtros = Filtros.do_request(request.GET)
    return render(request, 'crm/caixa.html', {
        **_contexto_lista(request, filtros, alvo.pk), **_contexto_pagina(alvo, request.user),
    })


@require_GET
@acesso_crm
def lista(request: HttpRequest) -> HttpResponse:
    filtros = Filtros.do_request(request.GET)
    atual = inteiro_ou_none(request.GET.get('atual'))
    return render(request, 'crm/parciais/lista.html', _contexto_lista(request, filtros, atual))


@require_GET
@acesso_crm
def parte(request: HttpRequest, pk: int, nome: str) -> HttpResponse:
    if nome not in PARTES:
        raise Http404
    alvo = get_object_or_404(Conversa, pk=pk)
    if nome == 'mensagens':
        _marcar_lida(alvo)
    contexto = _contexto_parte(alvo, request.user, nome)
    return render(request, PARTES[nome], {**contexto, 'filtros': Filtros.do_request(request.GET)})


@require_GET
@acesso_crm
def mensagens_antigas(request: HttpRequest, pk: int) -> HttpResponse:
    alvo = get_object_or_404(Conversa, pk=pk)
    antes = inteiro_ou_none(request.GET.get('antes'))
    qs = base_mensagens(alvo)
    if antes:
        qs = qs.filter(id__lt=antes)
    pagina = list(qs.order_by('-criado_em', '-id')[:LIMITE_MENSAGENS_DETALHE + 1])
    return render(request, 'crm/parciais/mensagens_antigas.html', {
        'mensagens': mensagens_dicts(list(reversed(pagina[:LIMITE_MENSAGENS_DETALHE]))),
        'tem_mais_antigas': len(pagina) > LIMITE_MENSAGENS_DETALHE,
        'conversa': {'id': alvo.pk, 'pode_responder': bloqueio_de(alvo, request.user) is None},
    })


@require_GET
@acesso_crm
def buscar_cliente(request: HttpRequest, pk: int) -> HttpResponse:
    alvo = get_object_or_404(Conversa, pk=pk)
    termo = request.GET.get('q', '')
    vinculados = set(alvo.clientes.values_list('id', flat=True))
    achados = [c for c in organizacao.buscar_clientes(request.user, termo) if c['id'] not in vinculados]
    return render(request, 'crm/parciais/busca_cliente.html', {
        'achados': achados, 'termo': termo.strip(), 'conversa': {'id': alvo.pk},
        'busca_curta': len(termo.strip()) < organizacao.MIN_BUSCA_CLIENTE,
    })
