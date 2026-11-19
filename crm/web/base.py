"""Base das telas do CRM no backoffice: permissão, leitura de campos e resposta das ações.

As ações aceitam dois jeitos de envio:
- pelo JS da caixa de entrada (cabeçalho X-Requested-With): respondem JSON e a tela
  recarrega só os trechos afetados;
- formulário comum (sem JS): mensagem no topo e volta para a conversa.
"""
from functools import wraps
from typing import Any, Callable

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from crm.permissoes import pode_acessar, pode_gerenciar
from crm.services.conversas import ConflitoCRM
from crm.services.midias import ErroMidia

STATUS_CONFLITO = 409
CABECALHO_AJAX = 'XMLHttpRequest'


def acesso_crm(view: Callable) -> Callable:
    """Só quem tem crm.acessar_crm (login já é exigido pelo middleware do backoffice)."""
    @wraps(view)
    def interna(request: HttpRequest, *args, **kwargs):
        if not pode_acessar(request.user):
            raise PermissionDenied('Você não tem acesso ao CRM de WhatsApp.')
        return view(request, *args, **kwargs)
    return interna


def gerencia_crm(view: Callable) -> Callable:
    @wraps(view)
    def interna(request: HttpRequest, *args, **kwargs):
        if not pode_gerenciar(request.user):
            raise PermissionDenied('Só quem gerencia o CRM pode fazer isso.')
        return view(request, *args, **kwargs)
    return interna


def eh_ajax(request: HttpRequest) -> bool:
    return request.headers.get('X-Requested-With') == CABECALHO_AJAX


def ler_inteiro(valor: Any, campo: str) -> int | None:
    if valor in (None, ''):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ConflitoCRM(f'Valor inválido para {campo}.')


def inteiro_ou_none(valor: Any) -> int | None:
    """Para parâmetros de leitura (GET): valor inválido é ignorado em vez de virar erro."""
    try:
        return int(valor) if valor not in (None, '') else None
    except (TypeError, ValueError):
        return None


def ler_datahora(valor: Any):
    """Aceita o formato do <input type="datetime-local"> (horário local do sistema)."""
    if not valor:
        return None
    data = parse_datetime(str(valor))
    if data is None:
        raise ConflitoCRM('Data e hora inválidas.')
    if timezone.is_naive(data):
        data = timezone.make_aware(data)
    return data


def destino_seguro(request: HttpRequest, padrao: str) -> str:
    """Volta para o `proxima` enviado pelo formulário só se for do próprio sistema."""
    proxima = request.POST.get('proxima') or request.GET.get('proxima') or ''
    if proxima and url_has_allowed_host_and_scheme(proxima, allowed_hosts={request.get_host()},
                                                    require_https=request.is_secure()):
        return proxima
    return padrao


def url_conversa(conversa_id: int) -> str:
    return reverse('crm:conversa', args=[conversa_id])


def responder(request: HttpRequest, destino: str, mensagem: str = '', dados: dict | None = None) -> HttpResponse:
    """Resposta de sucesso de uma ação."""
    if eh_ajax(request):
        return JsonResponse({'ok': True, 'mensagem': mensagem, **(dados or {})})
    if mensagem:
        messages.success(request, mensagem)
    return redirect(destino_seguro(request, destino))


def responder_erro(request: HttpRequest, destino: str, erro: str, motivo: str = '') -> HttpResponse:
    if eh_ajax(request):
        return JsonResponse({'ok': False, 'erro': erro, 'motivo': motivo}, status=STATUS_CONFLITO)
    messages.error(request, erro)
    return redirect(destino_seguro(request, destino))


def acao(view: Callable) -> Callable:
    """POST + acesso ao CRM + regra de negócio virando aviso (409 no JS, mensagem sem JS).

    A view devolve a resposta pronta (via `responder`) e só levanta ConflitoCRM/ErroMidia.
    O destino do erro é a conversa da URL (`pk`) ou a caixa de entrada.
    """
    @require_POST
    @acesso_crm
    @wraps(view)
    def interna(request: HttpRequest, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ConflitoCRM as erro:
            return responder_erro(request, _destino_do_erro(kwargs), erro.detail, erro.motivo)
        except ErroMidia as erro:
            return responder_erro(request, _destino_do_erro(kwargs), str(erro))
    return interna


def _destino_do_erro(kwargs: dict) -> str:
    conversa_id = kwargs.get('pk') or kwargs.get('conversa_id')
    return url_conversa(conversa_id) if conversa_id else reverse('crm:caixa')
