"""Códigos de erro da Meta → frase legível para a equipe (§13.4 da arquitetura)."""

MENSAGENS = {
    131026: 'O número não recebe mensagens (sem WhatsApp, número errado, bloqueou ou app desatualizado).',
    131047: 'Passaram mais de 24 h desde a última mensagem do cliente. Envie uma mensagem de abertura.',
    131042: 'Problema de pagamento na conta do WhatsApp Business.',
    131056: 'Muitas mensagens em pouco tempo para o mesmo número. Aguarde e tente de novo.',
    130472: 'A Meta não entregou esta mensagem de marketing a este contato. Use uma abertura de utilidade.',
    131049: 'A Meta não entregou esta mensagem de marketing a este contato. Use uma abertura de utilidade.',
    131050: 'O contato pediu para não receber mensagens de marketing.',
    131051: 'Tipo de mensagem não suportado pela Meta.',
    131052: 'Arquivo grande demais (acima de 100 MB).',
    131053: 'A Meta não aceitou este arquivo. Tente outro formato.',
    100: 'Parâmetro inválido na chamada à Meta.',
    190: 'O token do WhatsApp expirou ou é inválido. Gere um novo token do usuário do sistema.',
    10: 'O app não tem permissão para esta ação na Meta.',
    80007: 'Limite de chamadas à Meta atingido. Aguarde alguns minutos.',
    368: 'A conta foi temporariamente bloqueada pela Meta por violação de política.',
}

TEMPLATE_INDISPONIVEL = range(132000, 132017)


def traduzir_erro(codigo: int | None, titulo: str = '', detalhe: str = '') -> str:
    if codigo in MENSAGENS:
        base = MENSAGENS[codigo]
    elif codigo in TEMPLATE_INDISPONIVEL:
        base = 'A mensagem de abertura está indisponível na Meta (pausada, rejeitada ou com parâmetros errados).'
    else:
        base = detalhe or titulo or 'A Meta não entregou a mensagem.'
    return f'{base} (código {codigo})' if codigo else base
