"""Notificações do PagBank (`/api/pagbank/notificacao/`).

Assinatura `x-authenticity-token` obrigatória. O pedido é consultado de novo na API antes
da baixa. Responde 503 quando o PagBank não responde à consulta, para ele reenviar.
"""
import json
import logging

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import RegistroPagBank
from .pagbank import cliente
from .servicos.baixa import processar_notificacao

logger = logging.getLogger(__name__)

TAMANHO_MAXIMO = 64 * 1024  # notificações do PagBank são pequenas


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
        if not cliente.assinatura_valida(corpo_bruto, request.headers.get('x-authenticity-token', '')):
            # Sem gravar o corpo: quem não tem o token não enche o banco.
            logger.warning('Notificação do PagBank com assinatura inválida (%s bytes).', len(corpo_bruto))
            return HttpResponse(status=401)
        if not isinstance(corpo, dict):
            _registrar(None, cabecalhos, 400)
            return HttpResponse(status=400)
        try:
            cobranca = processar_notificacao(corpo, cabecalhos['x-product-id'])
        except cliente.ErroPagBank:
            _registrar(corpo, cabecalhos, 503)
            return HttpResponse(status=503)
        _registrar(corpo, cabecalhos, 200, cobranca)
        return HttpResponse(status=200)
