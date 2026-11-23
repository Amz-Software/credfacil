"""Dados de teste de contas a receber."""
import itertools
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from backoffice_api.models import RegistroAuditoria
from vendas.models import Cliente, ComprovantesCliente, Pagamento, TipoPagamento, Venda

URL_BASE = '/api/bo/v1/financeiro/'
_sequencia = itertools.count(1)


def tipo_ipx() -> TipoPagamento:
    tipo, _ = TipoPagamento.objects.get_or_create(nome='IPX', defaults={'parcelas': True, 'caixa': False})
    return tipo


def tipo_entrada() -> TipoPagamento:
    tipo, _ = TipoPagamento.objects.get_or_create(nome='ENTRADA', defaults={'parcelas': False, 'caixa': True})
    return tipo


def _vendedor():
    numero = next(_sequencia)
    return get_user_model().objects.create_user(
        username=f'vendedor{numero}', email=f'vendedor{numero}@teste.local', password='x',
    )


def criar_conta(
    loja,
    *,
    valor: str = '300.00',
    parcelas: int = 3,
    primeira: date | None = None,
    nome: str = 'Maria Silva',
    cpf: str = '12345678901',
    tipo: TipoPagamento | None = None,
) -> Pagamento:
    """Pagamento IPX com parcelas mensais (criadas pelo signal de `Pagamento`).

    Por padrão a 1ª parcela venceu há 40 dias: há parcela atrasada.
    """
    cliente = Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf=cpf, nascimento=date(1990, 1, 1), rg='123',
        cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém',
        comprovantes=ComprovantesCliente.objects.create(), loja=loja,
    )
    venda = Venda.objects.create(cliente=cliente, vendedor=_vendedor(), loja=loja, repasse_logista=Decimal('100.00'))
    return Pagamento.objects.create(
        venda=venda, tipo_pagamento=tipo or tipo_ipx(), valor=Decimal(valor), parcelas=parcelas, loja=loja,
        data_primeira_parcela=primeira or (date.today() - timedelta(days=40)),
    )


def parcelas_de(pagamento) -> list:
    return list(pagamento.parcelas_pagamento.order_by('numero_parcela'))


def ultima_auditoria(acao: str) -> RegistroAuditoria | None:
    return RegistroAuditoria.objects.filter(acao=acao).order_by('-id').first()


def ids(resposta) -> list[int]:
    return [item['id'] for item in resposta.json()['results']]
