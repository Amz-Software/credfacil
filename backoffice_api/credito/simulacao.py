"""Simulação do parcelamento da solicitação pela tabela `Parcelamento` da marca.

O cálculo é o de `vendas/services/venda.py:calcular_valores_venda` (o mesmo da
geração da venda); aqui só se repete a chamada para cada quantidade cadastrada.
"""
import copy
from decimal import Decimal

from produtos.models import Parcelamento
from vendas.models import AnaliseCreditoCliente
from vendas.services import ErroDeNegocio
from vendas.services.venda import calcular_valores_venda

CENTAVOS = Decimal('0.01')


def _dinheiro(valor: Decimal | None) -> str | None:
    if valor is None:
        return None
    return str(Decimal(valor).quantize(CENTAVOS))


def _numero_parcelas(analise: AnaliseCreditoCliente) -> int | None:
    try:
        return int(analise.numero_parcelas)
    except (TypeError, ValueError):
        return None


def _opcao(analise: AnaliseCreditoCliente, parcelamento: Parcelamento, escolhida: int | None) -> dict:
    # Cópia rasa: a análise original não é alterada.
    simulada = copy.copy(analise)
    simulada.numero_parcelas = str(parcelamento.qtd_vezes)
    valores = calcular_valores_venda(simulada)
    produto = analise.produto
    return {
        'qtd_vezes': parcelamento.qtd_vezes,
        'porcentagem_juros': _dinheiro(parcelamento.porcentagem_juros),
        'porcentagem_desconto': _dinheiro(parcelamento.porcentagem_desconto),
        'entrada': _dinheiro(valores.entrada),
        'valor_financiado': _dinheiro(produto.valor - valores.entrada),
        'valor_total': _dinheiro(valores.valor_credfacil),
        'valor_parcela': _dinheiro(valores.valor_credfacil / valores.parcelas),
        'repasse_logista': _dinheiro(valores.repasse_logista),
        'selecionada': parcelamento.qtd_vezes == escolhida,
    }


def simular_parcelamento(analise: AnaliseCreditoCliente) -> dict:
    """Opções de parcelamento da marca do produto, com a escolhida marcada.

    `erro` traz a mensagem da regra quando a simulação não é possível (produto
    sem valor, entrada abaixo da mínima...); `selecionada` é None quando a
    quantidade gravada não existe mais na tabela.
    """
    produto = analise.produto
    escolhida = _numero_parcelas(analise)
    base = {
        'valor_produto': _dinheiro(produto.valor),
        'entrada_minima': _dinheiro(produto.entrada_cliente),
        'numero_parcelas': escolhida,
        'opcoes': [],
        'selecionada': None,
        'erro': None,
    }
    if not produto.marca_id:
        return {**base, 'erro': 'Produto sem marca vinculada: não há parcelamento cadastrado.'}

    parcelamentos = Parcelamento.objects.filter(marca_id=produto.marca_id).order_by('qtd_vezes')
    try:
        opcoes = [_opcao(analise, parcelamento, escolhida) for parcelamento in parcelamentos]
    except ErroDeNegocio as erro:
        return {**base, 'erro': erro.mensagem}

    selecionada = next((opcao for opcao in opcoes if opcao['selecionada']), None)
    erro = None
    if not opcoes:
        erro = f"Nenhum parcelamento cadastrado para a marca '{produto.marca.nome}'."
    elif escolhida and selecionada is None:
        erro = f'Parcelamento de {escolhida}x não está cadastrado para a marca do produto.'
    return {**base, 'opcoes': opcoes, 'selecionada': selecionada, 'erro': erro}
