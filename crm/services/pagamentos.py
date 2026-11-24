"""Resumo das parcelas em aberto de um cliente (mesma regra da consulta pública por CPF)."""
from datetime import date
from decimal import Decimal

from crm.models import ConfiguracaoCRM

MAX_PAGAMENTOS_NO_TEXTO = 5


def formatar_reais(valor: Decimal) -> str:
    inteiro, centavos = f'{valor:,.2f}'.split('.')
    return f'R$ {inteiro.replace(",", ".")},{centavos}'


def _link(token_publico) -> str:
    """Link da página pública do pagamento (pelo token UUID4, nunca pelo id sequencial)."""
    base = ConfiguracaoCRM.obter().url_publica.strip().rstrip('/')
    return f'{base}/pagamento/{token_publico}/' if base else ''


def _produto(venda) -> str:
    item = venda.itens_venda.select_related('produto').first()
    return item.produto.nome if item and item.produto_id else f'Compra #{venda.pk}'


def _resumo_pagamento(pagamento, hoje: date) -> dict | None:
    abertas = [p for p in pagamento.parcelas_pagamento.all() if not p.pago]
    if not abertas:
        return None
    atrasadas = [p for p in abertas if p.data_vencimento < hoje and not p.pagamento_efetuado]
    a_vencer = sorted((p for p in abertas if p.data_vencimento >= hoje and not p.pagamento_efetuado),
                      key=lambda p: p.data_vencimento)
    proxima = a_vencer[0] if a_vencer else None
    return {
        'pagamento_id': pagamento.pk,
        'venda_id': pagamento.venda_id,
        'produto': _produto(pagamento.venda),
        'parcelas_abertas': len(abertas),
        'total_aberto': f'{sum((p.valor_restante for p in abertas), Decimal("0")):.2f}',
        'parcelas_atrasadas': len(atrasadas),
        'total_atrasado': f'{sum((p.valor_restante for p in atrasadas), Decimal("0")):.2f}',
        'em_confirmacao': sum(1 for p in abertas if p.pagamento_efetuado),
        'proxima': None if proxima is None else {
            'numero': proxima.numero_parcela, 'valor': f'{proxima.valor_restante:.2f}',
            'vencimento': proxima.data_vencimento.isoformat(),
        },
        'token_publico': str(pagamento.token_publico),
        'link_publico': _link(pagamento.token_publico),
    }


def pagamentos_em_aberto(clientes):
    """Pagamentos que ainda podem ter parcela a pagar (venda ativa, sem quitação, desativação ou devolução)."""
    from vendas.models import Pagamento

    return (Pagamento.objects
            .filter(venda__cliente__in=list(clientes), venda__is_deleted=False,
                    quitado=False, desativado=False, devolucao=False)
            .select_related('venda__loja').prefetch_related('parcelas_pagamento')
            .order_by('venda__data_venda'))


def resumo_dos_clientes(clientes) -> list[dict]:
    """Pagamentos com parcelas em aberto (venda ativa, sem quitação, desativação ou devolução)."""
    hoje = date.today()
    return [r for r in (_resumo_pagamento(p, hoje) for p in pagamentos_em_aberto(clientes)) if r]


def resumo_do_cliente(cliente) -> list[dict]:
    return resumo_dos_clientes([cliente])


def _data_br(iso: str) -> str:
    ano, mes, dia = iso.split('-')
    return f'{dia}/{mes}/{ano}'


def texto_resumo(nome: str, itens: list[dict]) -> str:
    """Texto pronto para o WhatsApp (negrito com *)."""
    primeiro = nome.split()[0] if nome else ''
    saudacao = f'{primeiro}, ' if primeiro else ''
    if not itens:
        return f'{saudacao}você não tem parcelas em aberto no momento. ✅'
    linhas = [f'{saudacao}estas são suas parcelas em aberto:']
    for item in itens[:MAX_PAGAMENTOS_NO_TEXTO]:
        linhas.append('')
        linhas.append(f'*{item["produto"]}*')
        linhas.append(f'• {item["parcelas_abertas"]} parcela(s) em aberto: {formatar_reais(Decimal(item["total_aberto"]))}')
        if item['parcelas_atrasadas']:
            linhas.append(f'• Em atraso: {item["parcelas_atrasadas"]} parcela(s), '
                          f'{formatar_reais(Decimal(item["total_atrasado"]))}')
        if item['proxima']:
            proxima = item['proxima']
            linhas.append(f'• Próxima: {proxima["numero"]}ª parcela de {formatar_reais(Decimal(proxima["valor"]))}, '
                          f'vence em {_data_br(proxima["vencimento"])}')
        if item['em_confirmacao']:
            linhas.append(f'• {item["em_confirmacao"]} pagamento(s) informado(s) aguardando confirmação')
        if item['link_publico']:
            linhas.append(f'Pagar com PIX: {item["link_publico"]}')
    if len(itens) > MAX_PAGAMENTOS_NO_TEXTO:
        linhas.append('')
        linhas.append(f'E mais {len(itens) - MAX_PAGAMENTOS_NO_TEXTO} compra(s). Fale com um atendente para ver tudo.')
    return '\n'.join(linhas)
