"""Chamadas HTTP à API do PagBank (pedidos e checkouts) e validação das notificações.

Toda chamada é gravada em `RegistroPagBank` (pedida na homologação), sem o token.
"""
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

URLS = {
    'sandbox': 'https://sandbox.api.pagseguro.com',
    'producao': 'https://api.pagseguro.com',
}
MENSAGEM_PADRAO = 'O PagBank não conseguiu gerar a cobrança agora. Tente de novo em alguns minutos.'


class ErroPagBank(Exception):
    def __init__(self, mensagem: str = MENSAGEM_PADRAO, *, status_http: int | None = None, detalhes=None):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status_http = status_http
        self.detalhes = detalhes


class PagBankNaoConfigurado(ErroPagBank):
    pass


def configurado() -> bool:
    return bool(getattr(settings, 'PAGBANK_TOKEN', ''))


def ambiente() -> str:
    return getattr(settings, 'PAGBANK_AMBIENTE', 'sandbox')


def _token() -> str:
    token = getattr(settings, 'PAGBANK_TOKEN', '')
    if not token:
        raise PagBankNaoConfigurado('O PagBank não está configurado no servidor (PAGBANK_TOKEN).')
    return token


def _registrar(metodo: str, caminho: str, corpo, status_http, resposta, cobranca) -> None:
    from pagamentos_online.models import RegistroPagBank

    try:
        RegistroPagBank.objects.create(
            tipo=RegistroPagBank.Tipo.CHAMADA, ambiente=ambiente(), metodo=metodo, caminho=caminho[:200],
            status_http=status_http, requisicao=corpo, resposta=resposta, cobranca=cobranca,
        )
    except Exception:  # noqa: BLE001 — o registro nunca impede a cobrança
        logger.exception('Falha ao gravar o registro da chamada ao PagBank.')


def _mensagem_de_erro(resposta: dict | None) -> str:
    erros = (resposta or {}).get('error_messages') or []
    descricoes = [e.get('description') for e in erros if isinstance(e, dict) and e.get('description')]
    return '; '.join(descricoes)


def requisitar(metodo: str, caminho: str, corpo: dict | None = None, *, cobranca=None) -> dict:
    url = f'{URLS[ambiente()]}{caminho}'
    cabecalhos = {
        'Authorization': f'Bearer {_token()}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    try:
        resposta_http = requests.request(
            metodo, url, json=corpo, headers=cabecalhos, timeout=settings.PAGBANK_TIMEOUT,
        )
    except requests.RequestException as erro:
        logger.warning('PagBank indisponível em %s %s: %s', metodo, caminho, erro)
        _registrar(metodo, caminho, corpo, None, {'erro_rede': str(erro)[:500]}, cobranca)
        raise ErroPagBank() from erro
    try:
        resposta = resposta_http.json()
    except ValueError:
        resposta = {'texto': resposta_http.text[:2000]}
    _registrar(metodo, caminho, corpo, resposta_http.status_code, resposta, cobranca)
    if resposta_http.status_code >= 400:
        detalhe = _mensagem_de_erro(resposta)
        logger.warning('PagBank recusou %s %s (%s): %s', metodo, caminho, resposta_http.status_code, detalhe)
        raise ErroPagBank(status_http=resposta_http.status_code, detalhes=detalhe or resposta)
    return resposta


def criar_pedido(corpo: dict, *, cobranca=None) -> dict:
    return requisitar('POST', '/orders', corpo, cobranca=cobranca)


def consultar_pedido(pedido_id: str, *, cobranca=None) -> dict:
    return requisitar('GET', f'/orders/{pedido_id}', cobranca=cobranca)


def criar_checkout(corpo: dict, *, cobranca=None) -> dict:
    return requisitar('POST', '/checkouts', corpo, cobranca=cobranca)


def assinatura_valida(corpo_bruto: bytes, assinatura: str) -> bool:
    """`x-authenticity-token` = sha256(token + '-' + corpo bruto), como manda a documentação."""
    if not assinatura or not configurado():
        return False
    esperado = hashlib.sha256(f'{_token()}-'.encode() + corpo_bruto).hexdigest()
    return hmac.compare_digest(esperado, assinatura.strip().lower())
