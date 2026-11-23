"""Link para o cliente pagar uma parcela.

Ponto único de troca do gateway: hoje devolve a página pública do pagamento
(/pagamento/<token>/, com o PIX); quando o gateway for escolhido, só esta função muda.
"""
from crm.services.pagamentos import _link


class LinkIndisponivel(Exception):
    """Sem endereço público configurado: não há link para mandar."""


def link_da_parcela(parcela) -> dict:
    url = _link(parcela.pagamento.token_publico)
    if not url:
        raise LinkIndisponivel('O endereço público do sistema não está configurado no CRM.')
    return {
        'url': url,
        'forma': 'pagina_publica_pix',
        'instrucao': f'Na página o cliente vê o PIX e escolhe a {parcela.numero_parcela}ª parcela para pagar.',
    }
