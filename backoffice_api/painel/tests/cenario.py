"""Massa de dados da carteira IPX para os testes do painel e dos relatórios."""
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.utils import timezone

from produtos.models import Marca, Produto
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ComprovantesCliente,
    Pagamento,
    Parcela,
    ProdutoVenda,
    TipoPagamento,
    Venda,
)

_SEQUENCIA = count(1)


def hoje() -> date:
    return timezone.now().date()


def dias(n: int) -> date:
    return hoje() + timedelta(days=n)


def tipo_pagamento(nome: str, **flags) -> TipoPagamento:
    tipo, _ = TipoPagamento.objects.get_or_create(nome=nome, defaults=flags)
    return tipo


def tipo_ipx() -> TipoPagamento:
    return tipo_pagamento('IPX', parcelas=True)


def tipo_entrada() -> TipoPagamento:
    return tipo_pagamento('ENTRADA', caixa=True)


def vendedor_padrao():
    User = get_user_model()
    user, _ = User.objects.get_or_create(username='vendedor_cenario', defaults={'email': 'vendedor@cenario.local'})
    return user


def criar_cliente(loja, nome: str, cpf: str | None = None, restricao: bool = False, **extras) -> Cliente:
    numero = next(_SEQUENCIA)
    return Cliente.objects.create(
        nome=nome, telefone=f'9199999{numero:04d}', cpf=cpf or f'{numero:011d}', nascimento=date(1990, 1, 1),
        rg='1', cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(restricao=restricao), **extras,
    )


def produto(nome: str = 'Galaxy A15') -> Produto:
    marca, _ = Marca.objects.get_or_create(nome='Samsung')
    item, _ = Produto.objects.get_or_create(
        nome=nome, defaults={'valor': Decimal('1200.00'), 'entrada_cliente': Decimal('200.00'), 'marca': marca},
    )
    return item


def criar_venda(loja, cliente, *, repasse='100.00', data_venda=None, vendedor=None, imei='', **extras) -> Venda:
    venda = Venda.objects.create(
        loja=loja, cliente=cliente, vendedor=vendedor or vendedor_padrao(),
        repasse_logista=Decimal(repasse), **extras,
    )
    if data_venda:
        Venda.objects.filter(pk=venda.pk).update(data_venda=data_venda)
        venda.refresh_from_db()
    ProdutoVenda.objects.create(
        venda=venda, produto=produto(), valor_unitario=Decimal('1200.00'), quantidade=1, imei=imei, loja=loja,
    )
    return venda


def criar_pagamento(venda, tipo, valor: str, parcelas: list[dict], **flags) -> Pagamento:
    """`parcelas`: dicts com vencimento, valor e, opcionalmente, pago/data_pagamento/valor_pago."""
    pagamento = Pagamento.objects.create(
        venda=venda, tipo_pagamento=tipo, valor=Decimal(valor), parcelas=len(parcelas) or 1,
        data_primeira_parcela=parcelas[0]['vencimento'] if parcelas else hoje(), loja=venda.loja, **flags,
    )
    # O sinal `criar_ou_atualizar_parcelas` gera parcelas automáticas; o cenário usa as próprias.
    Parcela.objects.filter(pagamento=pagamento).delete()
    for numero, dados in enumerate(parcelas, start=1):
        Parcela.objects.create(
            pagamento=pagamento, numero_parcela=numero, loja=venda.loja,
            valor=Decimal(dados.get('valor', '100.00')), data_vencimento=dados['vencimento'],
            pago=dados.get('pago', False), data_pagamento=dados.get('data_pagamento'),
            valor_pago=Decimal(dados['valor_pago']) if dados.get('valor_pago') else Decimal(0),
            pagamento_efetuado=dados.get('pagamento_efetuado', False),
            desconto=Decimal(dados.get('desconto', '0')),
        )
    return pagamento


def parcela(vencimento: date, valor: str = '100.00', **extras) -> dict:
    return {'vencimento': vencimento, 'valor': valor, **extras}


def paga(vencimento: date, data_pagamento: date, valor: str = '100.00', valor_pago: str | None = None) -> dict:
    return parcela(vencimento, valor, pago=True, data_pagamento=data_pagamento, valor_pago=valor_pago)


def criar_analise(cliente, *, status: str = 'EA', venda=None, numero_parcelas: str = '10', **extras):
    return AnaliseCreditoCliente.objects.create(
        cliente=cliente, produto=produto(), loja=cliente.loja, status=status, venda=venda,
        numero_parcelas=numero_parcelas, **extras,
    )


def montar_carteira(loja_a, loja_b) -> dict:
    """Carteira com todas as situações que o dashboard distingue.

    Loja A: venda com parcela paga/vencida/a vencer, cliente quitado, venda cancelada,
            parcela com pagamento efetuado (não conta como paga).
    Loja B: pagamento desativado, pagamento em cobrança e pagamento em devolução.
    """
    ipx, entrada = tipo_ipx(), tipo_entrada()
    maria = criar_cliente(loja_a, 'Maria Souza')
    venda_maria = criar_venda(loja_a, maria, repasse='800.00')
    criar_pagamento(venda_maria, entrada, '200.00', [paga(dias(-45), dias(-45), '200.00')])
    criar_pagamento(venda_maria, ipx, '400.00', [
        paga(dias(-45), dias(-40), valor_pago='90.00'),
        parcela(dias(-10)),
        parcela(dias(20)),
        parcela(dias(50), pagamento_efetuado=True),
    ])

    joao = criar_cliente(loja_a, 'João Lima')
    venda_joao = criar_venda(loja_a, joao, repasse='500.00')
    criar_pagamento(venda_joao, ipx, '200.00', [paga(dias(-60), dias(-60)), paga(dias(-30), dias(-31))])

    cancelada = criar_venda(loja_a, criar_cliente(loja_a, 'Cancelado'), repasse='999.00', is_deleted=True)
    criar_pagamento(cancelada, ipx, '100.00', [parcela(dias(-5))])

    ana = criar_cliente(loja_b, 'Ana Reis')
    venda_ana = criar_venda(loja_b, ana, repasse='300.00')
    criar_pagamento(venda_ana, ipx, '300.00', [parcela(dias(-20)), parcela(dias(10)), parcela(dias(40))], desativado=True)

    pedro = criar_cliente(loja_b, 'Pedro Alves')
    venda_pedro = criar_venda(loja_b, pedro, repasse='250.00')
    criar_pagamento(venda_pedro, ipx, '200.00', [parcela(dias(-15)), parcela(dias(15))], flag_atrasado=True)

    lia = criar_cliente(loja_b, 'Lia Costa')
    venda_lia = criar_venda(loja_b, lia, repasse='150.00')
    criar_pagamento(venda_lia, ipx, '200.00', [parcela(dias(-25)), paga(dias(-55), dias(-50))], devolucao=True)

    return {
        'maria': maria, 'joao': joao, 'ana': ana, 'pedro': pedro, 'lia': lia,
        'venda_maria': venda_maria, 'venda_joao': venda_joao, 'venda_ana': venda_ana,
        'venda_pedro': venda_pedro, 'venda_lia': venda_lia, 'cancelada': cancelada,
    }
