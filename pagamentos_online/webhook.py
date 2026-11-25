"""Notificações do PagBank (`/api/pagbank/notificacao/`).

O aviso nunca é a fonte da baixa: o pedido é sempre consultado de novo na API, com o nosso token.
- Com `x-authenticity-token`: precisa conferir, senão 401.
- Sem assinatura (o sandbox não manda): vale só como sinal para consultar o pedido, sem o atalho do
  cabeçalho `x-product-id` e sem encerrar cobranças; há um limite global por minuto. Com
  PAGBANK_EXIGIR_ASSINATURA, é recusado.
Responde 503 quando o PagBank não responde à consulta, para ele reenviar; 404 quando o pedido não existe.
"""
import json
import logging

from django.conf import settings
from django.core.cache import caches
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import RegistroPagBank
from .pagbank import cliente
from .servicos.baixa import processar_notificacao

logger = logging.getLogger(__name__)

TAMANHO_MAXIMO = 64 * 1024  # notificações do PagBank são pequenas
LIMITE_SEM_ASSINATURA = 300  # avisos sem assinatura por minuto (todos juntos)
JANELA_LIMITE = 60
PEDIDO_INEXISTENTE = {400, 404}


def _sem_assinatura_demais() -> bool:
    cache = caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')]
    chave = 'pagamentos_online:avisos_sem_assinatura'
    cache.add(chave, 0, timeout=JANELA_LIMITE)
    try:
        return cache.incr(chave) > LIMITE_SEM_ASSINATURA
    except ValueError:  # expirou entre o add e o incr
        cache.set(chave, 1, timeout=JANELA_LIMITE)
        return False


def _registrar(corpo, cabecalhos: dict, status_http: int, cobranca=None) -> None:
    try:
        RegistroPagBank.objects.create(
            tipo=RegistroPagBank.Tipo.NOTIFICACAO, ambiente=cliente.ambiente(), metodo='POST',
            caminho='/api/pagbank/notificacao/', status_http=status_http,
            requisicao={'cabecalhos': cabecalhos, 'corpo': corpo}, cobranca=cobranca,
        )
    except Exception:  # noqa: BLE001 — o registro nunca impede o processamento
        logger.exception('Falha ao gravar a notificação do PagBank.')


@method_decorator(csrf_exempt, name='dispatch')
class NotificacaoPagBankView(View):
    http_method_names = ['post']

    def post(self, request):
        corpo_bruto = request.body
        cabecalhos = {nome: request.headers.get(nome, '') for nome in ('x-product-origin', 'x-product-id')}
        if len(corpo_bruto) > TAMANHO_MAXIMO:
            return HttpResponse(status=413)
        try:
            corpo = json.loads(corpo_bruto)
        except ValueError:
            corpo = None
        assinatura = request.headers.get('x-authenticity-token', '')
        recusa = self._recusa(corpo_bruto, assinatura)
        if recusa:
            return recusa
        cabecalhos['assinado'] = bool(assinatura)
        if not isinstance(corpo, dict):
            _registrar(None, cabecalhos, 400)
            return HttpResponse(status=400)
        try:
            cobranca = processar_notificacao(corpo, cabecalhos['x-product-id'], assinado=bool(assinatura))
        except cliente.ErroPagBank as erro:
            status_http = 404 if erro.status_http in PEDIDO_INEXISTENTE else 503
            _registrar(corpo, cabecalhos, status_http)
            return HttpResponse(status=status_http)
        _registrar(corpo, cabecalhos, 200, cobranca)
        return HttpResponse(status=200)

    def _recusa(self, corpo_bruto: bytes, assinatura: str) -> HttpResponse | None:
        """Sem gravar o corpo nas recusas: quem não tem o token não enche o banco."""
        if assinatura:
            if cliente.assinatura_valida(corpo_bruto, assinatura):
                return None
            logger.warning('Notificação do PagBank com assinatura inválida (%s bytes).', len(corpo_bruto))
            return HttpResponse(status=401)
        if settings.PAGBANK_EXIGIR_ASSINATURA:
            logger.warning('Notificação do PagBank sem assinatura recusada (PAGBANK_EXIGIR_ASSINATURA).')
            return HttpResponse(status=401)
        if _sem_assinatura_demais():
            logger.warning('Avisos sem assinatura acima do limite: recusado.')
            return HttpResponse(status=429)
        return None
