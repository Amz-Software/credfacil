"""Menu de serviços da primeira mensagem: texto numerado + lista interativa do WhatsApp.

O cliente pode tocar em "Ver opções" (chega o nome do serviço), digitar o número ou
escrever do jeito dele: o assistente entende os três. Limites da Meta: até 10 itens,
título do item até 24 caracteres, botão até 20, corpo até 1024.
"""
from crm.models import ConfiguracaoCRM, Conversa, Mensagem

BOTAO = 'Ver opções'
SECAO = 'Serviços'
SERVICOS = (
    'Desbloquear o aparelho',
    'Parcela em atraso',
    'Chave PIX para pagamento',
    'Negociar minha dívida',
    'Oferta de quitação',
    'Antecipar parcela',
    'Valor da parcela',
    'IPX Consulta',
    'Outro assunto',
    'Falar com um atendente',
)
CORPO = (
    'Olá! Eu sou a {nome}, assistente virtual da {empresa} 😊\n'
    'Como posso te ajudar? Toque em *{botao}* ou responda com o número:\n\n'
    '{lista}\n\n'
    'E pra eu te atender melhor, qual é o seu nome?'
)


def lista_numerada() -> str:
    return '\n'.join(f'{numero}. {servico}' for numero, servico in enumerate(SERVICOS, start=1))


def corpo(config: ConfiguracaoCRM) -> str:
    return CORPO.format(nome=config.assistente_nome.strip() or 'Ana', empresa=config.nome_empresa.strip() or 'IPX',
                        botao=BOTAO, lista=lista_numerada())


def enviar(conversa: Conversa) -> Mensagem:
    from crm.services import envio

    itens = [(f'servico_{numero}', servico) for numero, servico in enumerate(SERVICOS, start=1)]
    return envio.enviar_lista(conversa, corpo(ConfiguracaoCRM.obter()), BOTAO, SECAO, itens,
                              dados={'ia': True, 'menu': True})
