"""Pagamento de uma parcela pelo assistente: link da página do cliente ou Pix direto (PagBank).

O link leva ao app do cliente (escolhe Pix, boleto ou cartão); sem o app configurado, à página
pública antiga, que tem o Pix da chave da empresa.
"""
from crm.services.pagamentos import formatar_reais
from vendas.services.erros import ErroDeNegocio


class LinkIndisponivel(Exception):
    """Sem endereço público configurado: não há link para mandar."""


def _online_disponivel() -> bool:
    from pagamentos_online.models import ConfiguracaoPagamentoOnline
    from pagamentos_online.servicos.cobrancas import disponivel

    configuracao = ConfiguracaoPagamentoOnline.obter()
    return disponivel(configuracao) and configuracao.pix_ativo


def link_da_parcela(parcela) -> dict:
    from pagamentos_online.servicos.links import link_do_pagamento

    url = link_do_pagamento(parcela.pagamento, parcela)
    if not url:
        raise LinkIndisponivel('O endereço público do sistema não está configurado no CRM.')
    if _online_disponivel():
        return {
            'url': url,
            'forma': 'pagina_do_cliente',
            'instrucao': (f'Na página o cliente escolhe Pix, boleto ou cartão para a {parcela.numero_parcela}ª '
                          'parcela. Pagando por lá, a baixa é automática: não precisa mandar comprovante.'),
        }
    return {
        'url': url,
        'forma': 'pagina_publica_pix',
        'instrucao': f'Na página o cliente vê o PIX e escolhe a {parcela.numero_parcela}ª parcela para pagar.',
    }


def pix_da_parcela(parcela) -> dict:
    """Gera (ou reaproveita) o Pix do PagBank. O copia e cola sai numa mensagem separada, pelo sistema."""
    from django.utils import timezone

    from pagamentos_online.models import Cobranca
    from pagamentos_online.servicos.cobrancas import gerar_cobranca

    if not _online_disponivel():
        raise ErroDeNegocio('O Pix automático não está disponível agora.')
    cobranca = gerar_cobranca(parcela, Cobranca.Forma.PIX, Cobranca.Origem.BOT)
    validade = timezone.localtime(cobranca.expira_em).strftime('%d/%m às %H:%M')
    return {
        'forma': 'pix',
        'valor': formatar_reais(cobranca.valor_total),
        'valido_ate': validade,
        'copia_cola': cobranca.pix_copia_cola,
        'instrucao': ('O código Pix copia e cola vai numa mensagem separada logo depois da sua resposta: não '
                      'escreva o código. Diga o valor, até quando vale e que a baixa é automática depois do '
                      'pagamento (não precisa de comprovante).'),
    }
