import re
from datetime import date

def calcular_data_primeira_parcela(dia_str: str) -> date:
    """
    Recebe dia_str em '1', '10' ou '20' e retorna um date
    correspondente ao próximo dia de pagamento.
    
    - Se hoje for <= dia, retorna esse mês no dia indicado.
    - Se hoje for > dia, retorna o dia indicado do próximo mês.
    """
    dia = int(dia_str)
    hoje = date.today()
    ano = hoje.year
    mes = hoje.month

    # Se ainda não chegamos ao dia no mês atual, usamos este mês
    if hoje.day <= dia:
        return date(ano, mes, dia)
    
    # Caso contrário, avançamos para o próximo mês
    if mes == 12:
        ano += 1
        mes = 1
    else:
        mes += 1

    return date(ano, mes, dia)


def formatar_cpf(cpf: str | None) -> str:
    """Formata um CPF armazenado como dígitos puros em 000.000.000-00.

    Devolve o valor original quando não houver exatamente 11 dígitos.
    """
    digitos = re.sub(r'\D', '', cpf or '')
    if len(digitos) != 11:
        return cpf or ''
    return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}'


def formatar_telefone(telefone: str | None) -> str:
    """Formata um telefone armazenado como dígitos puros em (00) 00000-0000.

    Suporta 10 (fixo) e 11 (celular) dígitos; devolve o valor original
    para qualquer outro tamanho.
    """
    digitos = re.sub(r'\D', '', telefone or '')
    if len(digitos) not in (10, 11):
        return telefone or ''
    ddd, restante = digitos[:2], digitos[2:]
    return f'({ddd}) {restante[:-4]}-{restante[-4:]}'
