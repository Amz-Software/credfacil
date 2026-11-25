"""Pagamento pelo assistente: link da página do cliente ou Pix direto (PagBank).

Vale para uma parcela, várias parcelas da mesma compra ou a quitação com o desconto do plano.
O link leva ao app do cliente (escolhe Pix, boleto ou cartão); sem o app configurado, à página
pública antiga, que tem o Pix da chave da empresa.
"""
from crm.services.pagamentos import formatar_reais
from vendas.services.erros import ErroDeNegocio


class LinkIndisponivel(Exception):
    """Sem endereço público configurado: não há link para mandar."""


def online_disponivel() -> bool:
    from pagamentos_online.models import ConfiguracaoPagamentoOnline
    from pagamentos_online.servicos.cobrancas import disponivel

    configuracao = ConfiguracaoPagamentoOnline.obter()
    return disponivel(configuracao) and configuracao.pix_ativo


def _o_que(parcelas: list, quitacao: bool) -> str:
    from pagamentos_online.servicos.planos import juntar

    if quitacao:
        return 'a quitação da compra'
    numeros = sorted(p.numero_parcela for p in parcelas)
    return f'a {numeros[0]}ª parcela' if len(numeros) == 1 else f'as parcelas {juntar(numeros)}'


def link_das_parcelas(parcelas: list, quitacao: bool = False) -> dict:
    from pagamentos_online.servicos.links import link_do_pagamento

    pagamento = parcelas[0].pagamento
    url = link_do_pagamento(pagamento, parcelas=parcelas, quitacao=quitacao)
    if not url:
        raise LinkIndisponivel('O endereço público do sistema não está configurado no CRM.')
    o_que = _o_que(parcelas, quitacao)
    if online_disponivel():
        return {
            'url': url,
            'forma': 'pagina_do_cliente',
            'instrucao': (f'Na página o cliente escolhe Pix, boleto ou cartão para {o_que}. Pagando por lá, a '
                          'baixa é automática: não precisa mandar comprovante.'),
        }
    return {
        'url': url,
        'forma': 'pagina_publica_pix',
        'instrucao': f'Na página o cliente vê o PIX para {o_que}.',
    }


def link_da_parcela(parcela) -> dict:
    return link_das_parcelas([parcela])


def pix_das_parcelas(parcelas: list, quitacao: bool = False) -> dict:
    """Gera (ou reaproveita) o Pix do PagBank. O copia e cola sai numa mensagem separada, pelo sistema."""
    from django.utils import timezone

    from pagamentos_online.models import Cobranca
    from pagamentos_online.servicos.cobrancas import gerar_cobranca_agrupada

    if not online_disponivel():
        raise ErroDeNegocio('O Pix automático não está disponível agora.')
    pagamento = parcelas[0].pagamento
    ids = None if quitacao else [p.pk for p in parcelas]
    cobranca = gerar_cobranca_agrupada(pagamento, Cobranca.Forma.PIX, Cobranca.Origem.BOT, ids, quitacao)
    validade = timezone.localtime(cobranca.expira_em).strftime('%d/%m às %H:%M')
    resultado = {
        'forma': 'pix',
        'valor': formatar_reais(cobranca.valor_total),
        'valido_ate': validade,
        'copia_cola': cobranca.pix_copia_cola,
        'instrucao': ('O código Pix copia e cola vai numa mensagem separada logo depois da sua resposta: não '
                      'escreva o código. Diga o valor, até quando vale e que a baixa é automática depois do '
                      'pagamento (não precisa de comprovante).'),
    }
    desconto = sum((item.desconto for item in cobranca.itens.all()), 0)
    if desconto:
        resultado['desconto_quitacao'] = formatar_reais(desconto)
    return resultado


def pix_da_parcela(parcela) -> dict:
    return pix_das_parcelas([parcela])
