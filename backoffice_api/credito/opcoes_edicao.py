"""Opções dos selects do formulário de edição da solicitação (produto, parcelas, vencimento, autenticador).

Lidas dos próprios forms de `vendas/forms.py` (os mesmos usados no PATCH), então a
SPA mostra exatamente o que o servidor aceita: produtos permitidos para a loja da
solicitação (mais o atual), parcelamentos cadastrados por marca e os números
autenticadores ativos da loja (só para ANALISTA/ADMINISTRADOR).
"""
from decimal import Decimal

from produtos.models import Parcelamento
from vendas.models import Cliente

from .edicao import _montar

CENTAVOS = Decimal('0.01')


def _dinheiro(valor) -> str | None:
    if valor is None:
        return None
    return str(Decimal(valor).quantize(CENTAVOS))


def _produtos(campo) -> list[dict]:
    produtos = campo.queryset.select_related('marca').order_by('nome')
    return [
        {
            'id': produto.pk,
            'nome': campo.label_from_instance(produto),
            'marca_id': produto.marca_id,
            'is_iphone': produto.is_iphone,
            'valor': _dinheiro(produto.valor),
            'entrada_cliente': _dinheiro(produto.entrada_cliente),
        }
        for produto in produtos
    ]


def _parcelas_por_marca(marcas: set[int]) -> dict[str, list[int]]:
    por_marca: dict[str, list[int]] = {str(marca): [] for marca in marcas}
    linhas = Parcelamento.objects.filter(marca_id__in=marcas).order_by('qtd_vezes').values_list('marca_id', 'qtd_vezes')
    for marca, qtd in linhas:
        por_marca[str(marca)].append(qtd)
    return por_marca


def _autenticadores(form) -> list[dict] | None:
    campo = form.fields.get('numero_autenticador')
    if campo is None:
        return None
    return [
        {'id': numero.pk, 'numero': numero.numero, 'descricao': numero.descricao}
        for numero in campo.queryset.order_by('numero')
    ]


def opcoes_de_edicao(cliente: Cliente, user) -> dict:
    form = _montar(cliente, user).analise
    produtos = _produtos(form.fields['produto'])
    marcas = {produto['marca_id'] for produto in produtos if produto['marca_id']}
    return {
        'produtos': produtos,
        'parcelas_por_marca': _parcelas_por_marca(marcas),
        'data_pagamento': [
            {'codigo': codigo, 'rotulo': rotulo}
            for codigo, rotulo in form.fields['data_pagamento'].choices
            if codigo
        ],
        'numeros_autenticadores': _autenticadores(form),
    }
