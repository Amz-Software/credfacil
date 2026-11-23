"""Configuração do CRM (só quem gerencia): geral, integração, cadastros, aberturas e simulador."""
import os
from typing import Any

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.views.decorators.http import require_http_methods, require_POST

from crm.apresentacao import abertura_dict, base_mensagens, mensagens_dicts
from crm.forms import ConfiguracaoForm, EtiquetaForm, RespostaRapidaForm
from crm.models import ConfiguracaoCRM, Conversa, Etiqueta, ModeloAbertura, RespostaRapida
from crm.services import aberturas, organizacao
from crm.services.conversas import ConflitoCRM
from crm.web.base import gerencia_crm, ler_inteiro
from crm.whatsapp import credenciais, obter_provider

CAMINHO_WEBHOOK = '/api/whatsapp/webhook/'
VARIAVEIS = (
    ('token', 'WHATSAPP_TOKEN', 'Token de acesso do usuário do sistema'),
    ('phone_number_id', 'WHATSAPP_PHONE_NUMBER_ID', 'Identificação do número'),
    ('waba_id', 'WHATSAPP_WABA_ID', 'Identificação da conta do WhatsApp Business'),
    ('app_secret', 'WHATSAPP_APP_SECRET', 'Chave secreta do app (assinatura do webhook)'),
    ('verify_token', 'WHATSAPP_VERIFY_TOKEN', 'Token de verificação do webhook'),
)
SIMULACOES = ('APROVADO', 'REJEITADO')
CHAVE_SIMULADOR = 'crm_simulador'
MENSAGENS_SIMULADOR = 15


def _simulado() -> bool:
    return bool(getattr(obter_provider(), 'simulado', False))


def _integracao(request: HttpRequest) -> dict[str, Any]:
    """Situação das credenciais. Nunca mostra valores, só se estão definidas."""
    cred = credenciais()
    itens = [{'variavel': variavel, 'descricao': descricao, 'ok': bool(getattr(cred, chave))}
             for chave, variavel, descricao in VARIAVEIS]
    return {
        'modo_real': cred.modo_real,
        'itens': itens,
        'transcricao': bool(os.environ.get('OPENAI_API_KEY', '').strip()),
        'api_version': cred.versao,
        'webhook_url': request.build_absolute_uri(CAMINHO_WEBHOOK),
        'privacidade_url': request.build_absolute_uri(reverse('politica_privacidade')),
    }


def _render(request: HttpRequest, template: str, aba: str, contexto: dict) -> HttpResponse:
    return render(request, f'crm/configuracao/{template}', {**contexto, 'aba': aba, 'simulado': _simulado()})


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def geral(request: HttpRequest) -> HttpResponse:
    form = ConfiguracaoForm(request.POST or None, instance=ConfiguracaoCRM.obter())
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuração salva.')
        return redirect('crm:configuracao')
    return _render(request, 'geral.html', 'geral', {'form': form, 'integracao': _integracao(request)})


# --- etiquetas e respostas rápidas (mesmo fluxo: lista + novo + edição) -------------------------

CADASTROS = {
    'etiquetas': {'modelo': Etiqueta, 'form': EtiquetaForm, 'titulo': 'Etiquetas', 'singular': 'etiqueta'},
    'respostas': {'modelo': RespostaRapida, 'form': RespostaRapidaForm, 'titulo': 'Respostas rápidas',
                  'singular': 'resposta rápida'},
}


def _config_cadastro(tipo: str) -> dict:
    if tipo not in CADASTROS:
        raise Http404
    return CADASTROS[tipo]


def _salvar_cadastro(request: HttpRequest, form) -> None:
    objeto = form.save(commit=False)
    if isinstance(objeto, RespostaRapida) and objeto.criado_por_id is None:
        objeto.criado_por = request.user
    objeto.save()


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def cadastro_lista(request: HttpRequest, tipo: str) -> HttpResponse:
    config = _config_cadastro(tipo)
    form = config['form'](request.POST or None)
    if request.method == 'POST' and form.is_valid():
        _salvar_cadastro(request, form)
        messages.success(request, f'{config["singular"].capitalize()} criada.')
        return redirect('crm:cadastro_lista', tipo=tipo)
    return _render(request, 'cadastro_lista.html', tipo, {
        'tipo': tipo, 'config': config, 'form': form, 'itens': config['modelo'].objects.all(),
    })


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def cadastro_editar(request: HttpRequest, tipo: str, pk: int) -> HttpResponse:
    config = _config_cadastro(tipo)
    objeto = get_object_or_404(config['modelo'], pk=pk)
    form = config['form'](request.POST or None, instance=objeto)
    if request.method == 'POST' and form.is_valid():
        _salvar_cadastro(request, form)
        messages.success(request, 'Alterações salvas.')
        return redirect('crm:cadastro_lista', tipo=tipo)
    return _render(request, 'cadastro_editar.html', tipo, {'tipo': tipo, 'config': config, 'form': form,
                                                           'objeto': objeto})


# --- mensagens de abertura (templates da Meta) --------------------------------------------------

def _aberturas_contexto(dados: dict | None = None) -> dict:
    modelos = ModeloAbertura.objects.prefetch_related('versoes')
    return {'modelos': [abertura_dict(m) for m in modelos], 'dados': dados or {}, 'simulacoes': SIMULACOES}


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def aberturas_lista(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        try:
            aberturas.criar_modelo(request.POST.get('titulo', ''), request.POST.get('corpo', ''), request.user)
        except ConflitoCRM as erro:
            messages.error(request, erro.detail)
            return _render(request, 'aberturas.html', 'aberturas', _aberturas_contexto(request.POST))
        messages.success(request, 'Mensagem enviada à Meta para aprovação.')
        return redirect('crm:aberturas')
    return _render(request, 'aberturas.html', 'aberturas', _aberturas_contexto())


def _dados_edicao(request: HttpRequest, atual: dict) -> dict:
    dados = {
        'titulo': request.POST.get('titulo', ''),
        'ordem': ler_inteiro(request.POST.get('ordem'), 'ordem') or 0,
        'ativo': request.POST.get('ativo') == 'on',
    }
    corpo = request.POST.get('corpo', '')
    corpo_atual = (atual.get('ultima') or {}).get('corpo', '')
    if corpo.strip() and corpo.strip() != corpo_atual.strip():
        dados['corpo'] = corpo
    return dados


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def abertura_editar(request: HttpRequest, pk: int) -> HttpResponse:
    modelo = get_object_or_404(ModeloAbertura.objects.prefetch_related('versoes'), pk=pk)
    atual = abertura_dict(modelo)
    if request.method == 'POST':
        try:
            dados = _dados_edicao(request, atual)
            aberturas.editar_modelo(modelo, dados, request.user)
        except ConflitoCRM as erro:
            messages.error(request, erro.detail)
        else:
            aviso = ' O texto novo foi enviado à Meta.' if 'corpo' in dados else ''
            messages.success(request, f'Alterações salvas.{aviso}')
            return redirect('crm:aberturas')
    return _render(request, 'abertura_editar.html', 'aberturas', {'modelo': atual, 'dados': request.POST})


@require_POST
@gerencia_crm
def abertura_verificar(request: HttpRequest, pk: int) -> HttpResponse:
    modelo = get_object_or_404(ModeloAbertura, pk=pk)
    for versao in modelo.versoes.exclude(status__in=['DESCARTADO', 'ERRO_ENVIO']):
        aberturas.sincronizar(versao)
    messages.success(request, 'Situação atualizada com a Meta.')
    return redirect('crm:aberturas')


@require_POST
@gerencia_crm
def abertura_simular(request: HttpRequest, pk: int) -> HttpResponse:
    try:
        aberturas.simular_decisao(get_object_or_404(ModeloAbertura, pk=pk), request.POST.get('status', ''))
    except ConflitoCRM as erro:
        messages.error(request, erro.detail)
    else:
        messages.success(request, 'Decisão da Meta simulada.')
    return redirect('crm:aberturas')


# --- simulador (só sem credenciais da Meta) ------------------------------------------------------

def _conversa_simulada(request: HttpRequest) -> dict | None:
    conversa_id = (request.session.get(CHAVE_SIMULADOR) or {}).get('conversa')
    conversa = Conversa.objects.filter(pk=conversa_id).first() if conversa_id else None
    if conversa is None:
        return None
    recentes = list(base_mensagens(conversa).order_by('-criado_em', '-id')[:MENSAGENS_SIMULADOR])
    return {'id': conversa.pk, 'nome': conversa.nome_exibicao, 'mensagens': mensagens_dicts(list(reversed(recentes)))}


@require_http_methods(['GET', 'POST'])
@gerencia_crm
def simulador(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        return _simular(request)
    return _render(request, 'simulador.html', 'simulador', {
        'ultimos': request.session.get(CHAVE_SIMULADOR) or {},
        'conversa_simulada': _conversa_simulada(request),
        'conversas': Conversa.objects.order_by('-ultima_mensagem_em')[:50],
    })


def _simular(request: HttpRequest) -> HttpResponse:
    if not _simulado():
        messages.error(request, 'O simulador só funciona sem as credenciais da Meta.')
        return redirect('crm:simulador')
    if request.POST.get('acao') == 'ler':
        conversa = get_object_or_404(Conversa, pk=ler_inteiro(request.POST.get('conversa'), 'conversa') or 0)
        alteradas = organizacao.simular_leitura(conversa)
        messages.success(request, f'{alteradas} mensagem(ns) marcada(s) como lida(s) pelo cliente.')
        return redirect('crm:simulador')
    texto = (request.POST.get('texto') or '').strip()
    telefone = (request.POST.get('telefone') or '').strip()
    nome = (request.POST.get('nome') or '').strip()
    if not texto or not telefone:
        messages.error(request, 'Informe o telefone e o texto.')
        return redirect('crm:simulador')
    mensagem = organizacao.simular_recebida(telefone, nome, texto)
    request.session[CHAVE_SIMULADOR] = {'telefone': telefone, 'nome': nome,
                                        'conversa': mensagem.conversa_id if mensagem else None}
    return redirect('crm:simulador')


urlpatterns = [
    path('configuracao/', geral, name='configuracao'),
    path('configuracao/aberturas/', aberturas_lista, name='aberturas'),
    path('configuracao/aberturas/<int:pk>/', abertura_editar, name='abertura_editar'),
    path('configuracao/aberturas/<int:pk>/verificar/', abertura_verificar, name='abertura_verificar'),
    path('configuracao/aberturas/<int:pk>/simular/', abertura_simular, name='abertura_simular'),
    path('configuracao/simulador/', simulador, name='simulador'),
    path('configuracao/<str:tipo>/', cadastro_lista, name='cadastro_lista'),
    path('configuracao/<str:tipo>/<int:pk>/', cadastro_editar, name='cadastro_editar'),
]
