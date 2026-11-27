"""Consulta das compras do cliente para o assistente: parcelas em aberto, parcelas já pagas e
compras quitadas (responde "quando paguei?", "quantas faltam?", "já quitei?").

Só o crediário IPX (`pagamentos.TIPO_CREDFACIL`): a ENTRADA é paga na loja e não é parcela.
"""
from datetime import date
from decimal import Decimal

from crm.services import pagamentos

MAX_COMPRAS = 5
MAX_PARCELAS_ABERTAS = 12
MAX_PARCELAS_PAGAS = 6  # as mais recentes; o total pago e a contagem cobrem o resto
SEM_DATA = 'data não registrada'


def _data(valor) -> str | None:
    return valor.strftime('%d/%m/%Y') if valor else None


def _situacao_aberta(parcela, hoje: date) -> str:
    if parcela.pagamento_efetuado:
        return 'pagamento informado, aguardando confirmação'
    return 'atrasada' if parcela.data_vencimento < hoje else 'a vencer'


def _loja(venda) -> dict:
    loja = venda.loja
    return {'nome': loja.nome, 'endereco': loja.endereco or ''} if loja else {}


def _paga(parcela) -> dict:
    return {
        'numero': parcela.numero_parcela,
        'valor_pago': pagamentos.formatar_reais(parcela.valor_pago_efetivo),
        'vencimento': _data(parcela.data_vencimento),
        'pago_em': _data(parcela.data_pagamento) or SEM_DATA,
    }


def _aberta(parcela, hoje: date) -> dict:
    return {
        'parcela_id': parcela.pk,
        'numero': parcela.numero_parcela,
        'valor': pagamentos.formatar_reais(parcela.valor_restante),
        'vencimento': _data(parcela.data_vencimento),
        'situacao': _situacao_aberta(parcela, hoje),
    }


def resumo_da_compra(pagamento, hoje: date) -> dict:
    """Uma compra: situação, quantas parcelas pagas de quantas, as pagas recentes e as em aberto."""
    todas = sorted(pagamento.parcelas_pagamento.all(), key=lambda p: (p.numero_parcela, p.pk))
    pagas = [p for p in todas if p.pago]
    abertas = [p for p in todas if not p.pago]
    quitada = pagamento.quitado or not abertas
    # Sem o nome do produto: o cliente pediu que o bot não descreva a compra (só valores e datas).
    compra = {
        'data_compra': _data(pagamento.venda.data_venda),
        'loja': _loja(pagamento.venda),
        'situacao': 'quitada' if quitada else 'em andamento',
        'parcelas_pagas': len(pagas),
        'total_parcelas': len(todas),
        'total_pago': pagamentos.formatar_reais(sum((p.valor_pago_efetivo for p in pagas), Decimal('0'))),
        'parcelas_pagas_recentes': [_paga(p) for p in pagas[-MAX_PARCELAS_PAGAS:]],
    }
    if quitada:
        datas = [p.data_pagamento for p in pagas if p.data_pagamento]
        compra['quitada_em'] = _data(max(datas)) if datas else SEM_DATA
        return compra
    atrasadas = [p for p in abertas if p.data_vencimento < hoje and not p.pagamento_efetuado]
    compra.update({
        'aparelho_bloqueado': bool(pagamento.bloqueado),
        'qtd_em_aberto': len(abertas),
        'qtd_atrasadas': len(atrasadas),
        'atrasada_mais_antiga': _data(min(p.data_vencimento for p in atrasadas)) if atrasadas else None,
        'total_em_aberto': pagamentos.formatar_reais(sum((p.valor_restante for p in abertas), Decimal('0'))),
        'total_atrasado': pagamentos.formatar_reais(sum((p.valor_restante for p in atrasadas), Decimal('0'))),
        'parcelas': [_aberta(p, hoje) for p in abertas[:MAX_PARCELAS_ABERTAS]],
    })
    return compra


def consultar(clientes, hoje: date) -> dict:
    """Compras em andamento primeiro, depois as quitadas (mais recentes antes)."""
    compras = [resumo_da_compra(p, hoje) for p in pagamentos.pagamentos_do_cliente(clientes)]
    compras.sort(key=lambda c: c['situacao'] == 'quitada')  # estável: mantém a ordem por data dentro de cada grupo
    resultado: dict = {'compras': compras[:MAX_COMPRAS]}
    if not compras:
        resultado['observacao'] = 'Nenhuma compra no crediário encontrada para este cliente.'
    elif all(c['situacao'] == 'quitada' for c in compras):
        resultado['observacao'] = 'Nenhuma parcela em aberto: todas as compras estão quitadas.'
    if len(compras) > MAX_COMPRAS:
        resultado['observacao'] = f'Há mais compras além destas {MAX_COMPRAS}; para ver todas, transfira.'
    return resultado
