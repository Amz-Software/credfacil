"""Cenário de vendas para os testes do módulo (venda manual e venda gerada por análise)."""
from datetime import date, timedelta
from decimal import Decimal

from estoque.models import EstoqueImei
from produtos.models import Marca, Parcelamento, Produto
from vendas.models import (
    AnaliseCreditoCliente,
    Cliente,
    ComprovantesCliente,
    Pagamento,
    ProdutoVenda,
    TipoPagamento,
    Venda,
)
from vendas.services.parcelas import calcular_data_primeira_parcela
from vendas.services.venda import gerar_venda_da_analise

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario  # noqa: F401

URL = '/api/bo/v1/vendas/'


def url_venda(venda, sufixo: str = '') -> str:
    return f'{URL}{venda.pk}/{sufixo}'


def criar_cliente(loja, nome: str = 'Maria Souza', cpf: str = '12345678901') -> Cliente:
    return Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf=cpf, nascimento=date(1990, 1, 1), rg='1234',
        cep='66000000', endereco='Rua A, 10', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(),
    )


def _dia_de_pagamento_valido() -> str:
    """Dia (1, 10 ou 20) com vencimento em até 30 dias a partir de hoje."""
    return next(dia for dia in ('1', '10', '20') if calcular_data_primeira_parcela(dia))


class CenarioVendas:
    """Lojas A e B, tipos ENTRADA/IPX (carnê), marca com parcelamento 10x e produto Android."""

    def montar_cenario(self):
        self.loja_a = criar_loja('Loja A')
        self.loja_b = criar_loja('Loja B')
        self.tipo_entrada, _ = TipoPagamento.objects.get_or_create(nome='ENTRADA', defaults={'caixa': True})
        self.tipo_ipx, _ = TipoPagamento.objects.get_or_create(
            nome='IPX', defaults={'parcelas': True, 'carne': True},
        )
        self.marca = Marca.objects.create(nome='Samsung')
        Parcelamento.objects.create(
            marca=self.marca, qtd_vezes=10, porcentagem_juros=Decimal('20'), porcentagem_desconto=Decimal('5'),
        )
        self.produto = Produto.objects.create(
            nome='Galaxy A15', valor=Decimal('1200.00'), entrada_cliente=Decimal('200.00'), marca=self.marca,
        )
        self.produto_novo = Produto.objects.create(
            nome='Galaxy A25', valor=Decimal('1500.00'), entrada_cliente=Decimal('300.00'), marca=self.marca,
        )
        self.vendedor = criar_usuario('vendedor', lojas=(self.loja_a,), acesso_backoffice=False)

    def criar_venda_manual(self, loja=None, *, cpf='12345678901', nome='Maria Souza', imei='350000000000001',
                           valor=Decimal('1000.00'), parcelas=4) -> Venda:
        loja = loja or self.loja_a
        venda = Venda.objects.create(
            loja=loja, cliente=criar_cliente(loja, nome, cpf), vendedor=self.vendedor,
            repasse_logista=Decimal('800.00'),
        )
        ProdutoVenda.objects.create(
            loja=loja, venda=venda, produto=self.produto, imei=imei, valor_unitario=valor, quantidade=1,
        )
        Pagamento.objects.create(
            loja=loja, venda=venda, tipo_pagamento=self.tipo_ipx, valor=valor, parcelas=parcelas,
            data_primeira_parcela=date.today() + timedelta(days=30),
        )
        return venda

    def criar_venda_da_analise(self, loja=None, *, cpf='98765432100', imei='350000000000099') -> Venda:
        loja = loja or self.loja_a
        cliente = criar_cliente(loja, 'João Análise', cpf)
        estoque = EstoqueImei.objects.create(produto=self.produto, imei=imei, loja=loja)
        AnaliseCreditoCliente.objects.create(
            cliente=cliente, produto=self.produto, loja=loja, status='A', status_aplicativo='I',
            imei=estoque, data_pagamento=_dia_de_pagamento_valido(), numero_parcelas='10',
        )
        return gerar_venda_da_analise(cliente, self.vendedor, bloquear_imei_de_venda_cancelada=True)
