"""Menu de serviços da primeira mensagem: texto numerado + lista interativa do WhatsApp.

O cliente pode tocar em "Ver opções" (chega o nome do serviço), digitar o número ou
escrever do jeito dele: o assistente entende os três. Limites da Meta: até 10 itens,
título do item até 24 caracteres, botão até 20, corpo até 1024.
"""
from crm.models import ConfiguracaoCRM, Conversa, Mensagem

BOTAO = 'Ver opções'
SECAO = 'Serviços'
# Número de cada serviço no menu (os atalhos e o roteiro do prompt usam estes números).
DESBLOQUEIO, ATRASO, PIX, NEGOCIAR, QUITACAO, ANTECIPAR, VALOR, CONSULTA, NOVO_APARELHO, ATENDENTE = range(1, 11)
SERVICOS = (
    'Desbloquear o aparelho',
    'Parcela em atraso',
    'Chave PIX para pagamento',
    'Negociar minha dívida',
    'Oferta de quitação',
    'Antecipar parcela',
    'Valor da parcela',
    'IPX Consulta',
    'Já quitei, novo aparelho',
    'Falar com um atendente',
)
CORPO = (
    'Olá! Eu sou a {nome}, assistente virtual da {empresa} 😊\n'
    'Como posso te ajudar? Toque em *{botao}* ou responda com o número:\n\n'
    '{lista}'
)


def lista_numerada() -> str:
    return '\n'.join(f'{numero}. {servico}' for numero, servico in enumerate(SERVICOS, start=1))


def numero_do_servico(texto: str) -> int | None:
    """Número do serviço pelo título (toque na lista) ou pelo número digitado; None se não for opção."""
    limpo = texto.strip().rstrip('.').strip()
    titulos = {servico.lower(): numero for numero, servico in enumerate(SERVICOS, start=1)}
    if limpo.lower() in titulos:
        return titulos[limpo.lower()]
    if limpo.isdigit() and 1 <= int(limpo) <= len(SERVICOS):
        return int(limpo)
    return None


def corpo(config: ConfiguracaoCRM) -> str:
    return CORPO.format(nome=config.assistente_nome.strip() or 'Ana', empresa=config.nome_empresa.strip() or 'IPX',
                        botao=BOTAO, lista=lista_numerada())


def enviar(conversa: Conversa) -> Mensagem:
    from crm.services import envio

    itens = [(f'servico_{numero}', servico) for numero, servico in enumerate(SERVICOS, start=1)]
    return envio.enviar_lista(conversa, corpo(ConfiguracaoCRM.obter()), BOTAO, SECAO, itens,
                              dados={'ia': True, 'menu': True})
