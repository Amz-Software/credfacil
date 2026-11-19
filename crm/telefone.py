"""Normalização de telefones brasileiros para casar o `wa_id` da Meta com cadastros.

O `wa_id` de celular brasileiro pode chegar sem o 9º dígito (55 + DDD + 8 dígitos),
e os cadastros guardam o número em formatos variados. A comparação usa uma "chave"
sem o 9º dígito; a resposta sempre vai para o `wa_id` recebido.
"""
import re

DDI_BRASIL = '55'
TAMANHO_NACIONAL_FIXO = 10       # DDD + 8 dígitos
TAMANHO_NACIONAL_CELULAR = 11    # DDD + 9 + 8 dígitos
TAMANHO_CHAVE_CELULAR = 13       # 55 + DDD + 9 + 8 dígitos
DIGITOS_SUFIXO_BUSCA = 8


def somente_digitos(valor: str | None) -> str:
    return re.sub(r'\D', '', valor or '')


def com_ddi(numero: str | None) -> str:
    """Só dígitos, com 55 na frente quando o número parece nacional."""
    digitos = somente_digitos(numero)
    if len(digitos) in (TAMANHO_NACIONAL_FIXO, TAMANHO_NACIONAL_CELULAR):
        return DDI_BRASIL + digitos
    return digitos


def chave_telefone(numero: str | None) -> str:
    """Forma canônica para comparação: E.164 sem o 9º dígito de celular brasileiro."""
    digitos = com_ddi(numero)
    eh_celular_com_nove = (
        len(digitos) == TAMANHO_CHAVE_CELULAR
        and digitos.startswith(DDI_BRASIL)
        and digitos[4] == '9'
    )
    if eh_celular_com_nove:
        return digitos[:4] + digitos[5:]
    return digitos


def mesmo_telefone(a: str | None, b: str | None) -> bool:
    chave_a, chave_b = chave_telefone(a), chave_telefone(b)
    return bool(chave_a) and chave_a == chave_b


def sufixo_busca(numero: str | None) -> str:
    """Últimos dígitos usados para pré-filtrar no banco antes de comparar a chave."""
    return chave_telefone(numero)[-DIGITOS_SUFIXO_BUSCA:]


def formatar_telefone(numero: str | None) -> str:
    """Formato de exibição: +55 (91) 99999-0000. Sem padrão conhecido, devolve os dígitos."""
    digitos = com_ddi(numero)
    if not digitos.startswith(DDI_BRASIL) or len(digitos) not in (12, 13):
        return digitos
    ddd, resto = digitos[2:4], digitos[4:]
    return f'+55 ({ddd}) {resto[:-4]}-{resto[-4:]}'
