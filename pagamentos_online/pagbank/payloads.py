"""Monta o JSON enviado ao PagBank e lê as respostas. Funções puras, sem banco nem rede.

Formatos conforme developer.pagbank.com.br (pedido com Pix em `charges`, boleto, checkout).
"""
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

PAGO = 'PAID'
CANCELADO = {'CANCELED', 'DECLINED'}
CHECKOUT_ENCERRADO = {'EXPIRED', 'INACTIVE'}
TAMANHO_DESCRICAO = 64


@dataclass(frozen=True)
class Pagador:
    nome: str
    cpf: str
    email: str
    telefone: str
    endereco: str
    bairro: str
    cidade: str
    uf: str
    cep: str


@dataclass(frozen=True)
class Cobrar:
    referencia: str
    descricao: str
    valor: Decimal
    pagador: Pagador
    url_notificacao: str


@dataclass(frozen=True)
class SituacaoPedido:
    pedido_id: str
    referencias: tuple[str, ...]
    pago: bool
    cancelado: bool
    pago_em: datetime | None
    valor_pago: Decimal | None
    detalhes: dict


def centavos(valor: Decimal) -> int:
    return int((Decimal(valor) * 100).quantize(Decimal('1')))


def _digitos(texto: str) -> str:
    return re.sub(r'\D', '', texto or '')


def _iso(momento: datetime) -> str:
    return timezone.localtime(momento).isoformat(timespec='seconds')


def _telefones(telefone: str) -> list[dict]:
    numero = _digitos(telefone)
    if len(numero) in (12, 13) and numero.startswith('55'):
        numero = numero[2:]
    if len(numero) not in (10, 11):
        return []
    return [{'country': '55', 'area': numero[:2], 'number': numero[2:], 'type': 'MOBILE'}]


def _cliente(pagador: Pagador) -> dict:
    cliente = {'name': pagador.nome[:120], 'email': pagador.email, 'tax_id': _digitos(pagador.cpf)}
    telefones = _telefones(pagador.telefone)
    if telefones:
        cliente['phones'] = telefones
    return cliente


def _itens(cobrar: Cobrar) -> list[dict]:
    return [{
        'reference_id': cobrar.referencia, 'name': cobrar.descricao[:TAMANHO_DESCRICAO],
        'quantity': 1, 'unit_amount': centavos(cobrar.valor),
    }]


def _cobranca(cobrar: Cobrar, metodo: dict) -> dict:
    return {
        'reference_id': cobrar.referencia,
        'description': cobrar.descricao[:TAMANHO_DESCRICAO],
        'amount': {'value': centavos(cobrar.valor), 'currency': 'BRL'},
        'payment_method': metodo,
    }


def _pedido(cobrar: Cobrar, metodo: dict) -> dict:
    return {
        'reference_id': cobrar.referencia,
        'customer': _cliente(cobrar.pagador),
        'items': _itens(cobrar),
        'charges': [_cobranca(cobrar, metodo)],
        'notification_urls': [cobrar.url_notificacao],
    }


def pedido_pix(cobrar: Cobrar, expira_em: datetime) -> dict:
    return _pedido(cobrar, {'type': 'PIX', 'pix': {'expiration_date': _iso(expira_em)}})


def _endereco(pagador: Pagador) -> dict:
    return {
        'street': (pagador.endereco or 'Não informado')[:160],
        'number': 'S/N',
        'locality': (pagador.bairro or 'Centro')[:60],
        'city': (pagador.cidade or 'Belém')[:90],
        'region': pagador.uf,
        'region_code': pagador.uf,
        'country': 'BRA',
        'postal_code': _digitos(pagador.cep)[:8],
    }


def pedido_boleto(cobrar: Cobrar, vencimento: date, instrucao: str) -> dict:
    pagador = cobrar.pagador
    boleto = {
        'due_date': vencimento.isoformat(),
        'instruction_lines': {'line_1': instrucao[:75], 'line_2': 'Não receber após o vencimento.'},
        'holder': {
            'name': pagador.nome[:120], 'tax_id': _digitos(pagador.cpf), 'email': pagador.email,
            'address': _endereco(pagador),
        },
    }
    return _pedido(cobrar, {'type': 'BOLETO', 'boleto': boleto})


def checkout_cartao(cobrar: Cobrar, expira_em: datetime, max_parcelas: int, url_retorno: str) -> dict:
    """Só cartão de crédito; sem INTEREST_FREE_INSTALLMENTS os juros do parcelamento ficam com o comprador."""
    corpo = {
        'reference_id': cobrar.referencia,
        'expiration_date': _iso(expira_em),
        'customer_modifiable': True,
        'items': _itens(cobrar),
        'payment_methods': [{'type': 'CREDIT_CARD'}],
        'payment_methods_configs': [{
            'type': 'CREDIT_CARD',
            'config_options': [{'option': 'INSTALLMENTS_LIMIT', 'value': str(max_parcelas)}],
        }],
        'notification_urls': [cobrar.url_notificacao],
        'payment_notification_urls': [cobrar.url_notificacao],
    }
    if url_retorno:
        corpo['redirect_url'] = url_retorno[:255]
        corpo['return_url'] = url_retorno[:255]
    return corpo


def _primeira_cobranca(resposta: dict) -> dict:
    cobrancas = resposta.get('charges') or []
    return cobrancas[0] if cobrancas else {}


def _link(links: list | None, rel: str, media: str | None = None) -> str:
    for link in links or []:
        if link.get('rel') == rel and (media is None or link.get('media') == media):
            return link.get('href') or ''
    return ''


def ler_pix(resposta: dict) -> dict:
    cobranca = _primeira_cobranca(resposta)
    qr_code = cobranca.get('qr_code') or {}
    texto = qr_code.get('text') or ''
    imagem = _link(cobranca.get('links'), 'QRCODE.PNG') or _link(qr_code.get('links'), 'QRCODE.PNG')
    if not texto:  # formato antigo: qr_codes no nível do pedido
        antigos = resposta.get('qr_codes') or [{}]
        texto = antigos[0].get('text') or ''
        imagem = imagem or _link(antigos[0].get('links'), 'QRCODE.PNG')
    return {'pix_copia_cola': texto, 'qr_code_url': imagem}


def ler_boleto(resposta: dict) -> dict:
    cobranca = _primeira_cobranca(resposta)
    boleto = (cobranca.get('payment_method') or {}).get('boleto') or {}
    return {
        'boleto_linha_digitavel': boleto.get('formatted_barcode') or boleto.get('barcode') or '',
        'boleto_pdf_url': _link(cobranca.get('links'), 'SELF', 'application/pdf'),
    }


def ler_checkout(resposta: dict) -> dict:
    return {'link_pagamento': _link(resposta.get('links'), 'PAY')}


def _momento(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace('Z', '+00:00'))
    except ValueError:
        return None


def _referencias(pedido: dict) -> tuple[str, ...]:
    candidatas = [pedido.get('reference_id')]
    candidatas += [item.get('reference_id') for item in pedido.get('items') or []]
    candidatas += [cobranca.get('reference_id') for cobranca in pedido.get('charges') or []]
    return tuple(dict.fromkeys(c for c in candidatas if c))


def _detalhes(cobranca: dict) -> dict:
    metodo = cobranca.get('payment_method') or {}
    cartao = metodo.get('card') or {}
    detalhes = {
        'cobranca_id': cobranca.get('id', ''),
        'tipo': metodo.get('type', ''),
        'end_to_end_id': (metodo.get('pix') or {}).get('end_to_end_id', ''),
        'parcelas_cartao': metodo.get('installments'),
        'bandeira': cartao.get('brand', ''),
        'final_cartao': cartao.get('last_digits', ''),
    }
    return {chave: valor for chave, valor in detalhes.items() if valor}


def _valor_pago(cobranca: dict) -> Decimal | None:
    valor = cobranca.get('amount') or {}
    em_centavos = (valor.get('summary') or {}).get('paid') or valor.get('value')
    return Decimal(em_centavos) / 100 if em_centavos is not None else None


def situacao_pedido(pedido: dict) -> SituacaoPedido:
    cobrancas = pedido.get('charges') or []
    paga = next((c for c in cobrancas if c.get('status') == PAGO), None)
    cancelado = paga is None and bool(cobrancas) and all(c.get('status') in CANCELADO for c in cobrancas)
    return SituacaoPedido(
        pedido_id=pedido.get('id', ''),
        referencias=_referencias(pedido),
        pago=paga is not None,
        cancelado=cancelado,
        pago_em=_momento(paga.get('paid_at')) if paga else None,
        valor_pago=_valor_pago(paga) if paga else None,
        detalhes=_detalhes(paga) if paga else {},
    )
