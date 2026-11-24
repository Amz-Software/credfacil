"""Link que o cliente recebe para pagar: a página dele no app (escolhe Pix, boleto ou cartão lá).

Sem o endereço do app configurado, cai na página pública antiga do Django.
"""
from crm.services.pagamentos import _link as link_pagina_antiga
from crm.services.pagamentos import formatar_reais
from vendas.models import Pagamento, Parcela
from vendas.services.erros import ErroDeNegocio

from ..models import ConfiguracaoPagamentoOnline

MENSAGEM_JANELA_FECHADA = ('O cliente não conversou com a gente no WhatsApp nas últimas 24 horas. '
                           'Copie o link e envie por outro meio.')


def link_do_pagamento(pagamento: Pagamento, parcela: Parcela | None = None) -> str:
    configuracao = ConfiguracaoPagamentoOnline.obter()
    caminho = f'pagamento/{pagamento.token_publico}'
    if parcela is not None:
        caminho += f'?parcela={parcela.pk}'
    return configuracao.link_app(caminho) or link_pagina_antiga(pagamento.token_publico)


def texto_do_link(parcela: Parcela, link: str) -> str:
    primeiro_nome = (parcela.pagamento.venda.cliente.nome or '').split(' ')[0]
    return (f'Olá, {primeiro_nome}! Segue o link para pagar a parcela {parcela.numero_parcela} '
            f'({formatar_reais(parcela.valor_restante)}). Lá você escolhe Pix, boleto ou cartão:\n{link}')


def enviar_link_whatsapp(parcela: Parcela, usuario) -> str:
    from crm.models import Mensagem
    from crm.services import envio

    link = link_do_pagamento(parcela.pagamento, parcela)
    if not link:
        raise ErroDeNegocio('Configure o endereço do app do cliente ou o endereço público do sistema.')
    cliente = parcela.pagamento.venda.cliente
    conversa = next((c for c in cliente.conversas_whatsapp.all() if c.janela_aberta()), None)
    if conversa is None:
        raise ErroDeNegocio(MENSAGEM_JANELA_FECHADA)
    envio.enviar_texto(conversa, texto_do_link(parcela, link), usuario=usuario, autor=Mensagem.Autor.HUMANO,
                       origem='pagamento_online', exigir_trava=False)
    return link
