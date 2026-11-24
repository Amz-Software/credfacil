"""Dados de teste da cobrança: cliente com venda IPX e parcelas com vencimento escolhido."""
from datetime import date, timedelta
from decimal import Decimal

from vendas.models import Cliente, ComprovantesCliente, Loja, Pagamento, Parcela, TipoPagamento, Venda

VALOR_PARCELA = Decimal('100.00')


def criar_cliente(loja: Loja, nome: str, telefone: str, cpf: str) -> Cliente:
    return Cliente.objects.create(
        nome=nome, telefone=telefone, cpf=cpf, nascimento=date(1990, 5, 17), rg='1', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(loja=loja),
    )


def criar_parcelas(cliente: Cliente, vendedor, vencimentos: list[date]) -> list[Parcela]:
    """Venda com pagamento IPX e uma parcela (em aberto) para cada vencimento."""
    tipo, _ = TipoPagamento.objects.get_or_create(nome='IPX', defaults={'parcelas': True, 'caixa': False})
    venda = Venda.objects.create(cliente=cliente, vendedor=vendedor, loja=cliente.loja,
                                 repasse_logista=Decimal('100.00'))
    pagamento = Pagamento.objects.create(venda=venda, tipo_pagamento=tipo, valor=VALOR_PARCELA * len(vencimentos),
                                         parcelas=len(vencimentos), loja=cliente.loja,
                                         data_primeira_parcela=date.today() + timedelta(days=1))
    parcelas = list(Parcela.objects.filter(pagamento=pagamento).order_by('numero_parcela'))
    for parcela, vencimento in zip(parcelas, vencimentos):
        Parcela.objects.filter(pk=parcela.pk).update(data_vencimento=vencimento, valor=VALOR_PARCELA)
    return list(Parcela.objects.filter(pagamento=pagamento).order_by('numero_parcela'))
