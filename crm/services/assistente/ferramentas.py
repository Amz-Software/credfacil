"""Ferramentas que o modelo pode pedir. Toda regra de acesso é conferida aqui, não no prompt.

A lista DEFINICOES tem ordem e texto fixos: ela entra no prefixo cacheado do prompt.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from crm.models import Conversa
from crm.services import pagamentos
from crm.services.assistente import identidade
from crm.services.links_pagamento import LinkIndisponivel, link_da_parcela

MAX_COMPRAS = 5
MAX_PARCELAS_POR_COMPRA = 12
MAX_MOTIVO = 1000

DEFINICOES = [
    {
        'name': 'identificar_cliente',
        'description': (
            'Confere a identidade do cliente pelo CPF e pela data de nascimento que ELE digitou nesta conversa. '
            'Obrigatório antes de consultar parcelas ou gerar link. Nunca invente nem complete dados.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'cpf': {'type': 'string', 'description': 'CPF como o cliente digitou (com ou sem pontuação).'},
                'data_nascimento': {'type': 'string', 'description': 'Data de nascimento, ex.: 17/05/1990.'},
            },
            'required': ['cpf', 'data_nascimento'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'consultar_parcelas',
        'description': (
            'Lista as compras e as parcelas em aberto do cliente já identificado: número, valor, vencimento e '
            'situação de cada parcela, com o parcela_id usado para gerar o link de pagamento.'
        ),
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'gerar_link_pagamento',
        'description': 'Gera o link para o cliente identificado pagar uma parcela em aberto (use o parcela_id).',
        'input_schema': {
            'type': 'object',
            'properties': {'parcela_id': {'type': 'integer', 'description': 'parcela_id vindo de consultar_parcelas.'}},
            'required': ['parcela_id'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'transferir_para_atendente',
        'description': (
            'Passa a conversa para a equipe humana. Depois, avise o cliente em uma frase curta que um atendente '
            'vai continuar por aqui. Use uma vez só.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'motivo': {
                    'type': 'string',
                    'description': 'Nota interna para a equipe: quem é o cliente, o que pediu e o que ficou pendente.',
                },
            },
            'required': ['motivo'],
            'additionalProperties': False,
        },
    },
]


class ErroFerramenta(Exception):
    """Erro explicável: volta ao modelo como tool_result com is_error."""


@dataclass
class Turno:
    """Efeitos de um turno do assistente (uma resposta ao cliente)."""

    conversa: Conversa
    transferiu: bool = False
    usou_dados: bool = False  # a resposta pode conter dados do cliente (o histórico oculta se a identidade expirar)


def _reais(valor: Decimal) -> str:
    return pagamentos.formatar_reais(valor)


def _clientes_liberados(turno: Turno):
    from vendas.models import Cliente

    ids = identidade.clientes_verificados(turno.conversa)
    if not ids:
        raise ErroFerramenta('Cliente ainda não identificado. Peça o CPF e a data de nascimento e use '
                             'identificar_cliente antes.')
    return Cliente.objects.filter(pk__in=ids)


def _situacao(parcela, hoje: date) -> str:
    if parcela.pagamento_efetuado:
        return 'pagamento informado, aguardando confirmação'
    return 'atrasada' if parcela.data_vencimento < hoje else 'a vencer'


def _compra(pagamento, hoje: date) -> dict | None:
    abertas = sorted((p for p in pagamento.parcelas_pagamento.all() if not p.pago),
                     key=lambda p: p.numero_parcela)
    if not abertas:
        return None
    atrasadas = [p for p in abertas if p.data_vencimento < hoje and not p.pagamento_efetuado]
    return {
        'produto': pagamentos._produto(pagamento.venda),
        'total_em_aberto': _reais(sum((p.valor_restante for p in abertas), Decimal('0'))),
        'total_atrasado': _reais(sum((p.valor_restante for p in atrasadas), Decimal('0'))),
        'parcelas': [
            {'parcela_id': p.pk, 'numero': p.numero_parcela, 'valor': _reais(p.valor_restante),
             'vencimento': p.data_vencimento.strftime('%d/%m/%Y'), 'situacao': _situacao(p, hoje)}
            for p in abertas[:MAX_PARCELAS_POR_COMPRA]
        ],
    }


def _identificar(turno: Turno, entrada: dict) -> dict:
    try:
        clientes = identidade.identificar(turno.conversa, entrada.get('cpf', ''), entrada.get('data_nascimento', ''))
    except identidade.ErroIdentificacao as erro:
        raise ErroFerramenta(str(erro)) from erro
    turno.usou_dados = True
    nome = (clientes[0].nome or '').split()
    return {'identificado': True, 'primeiro_nome': nome[0] if nome else ''}


def _consultar(turno: Turno, entrada: dict) -> dict:
    hoje = date.today()
    compras: list[dict] = []
    for pagamento in pagamentos.pagamentos_em_aberto(_clientes_liberados(turno)):
        compra = _compra(pagamento, hoje)
        if compra:
            compras.append(compra)
        if len(compras) > MAX_COMPRAS:
            break
    turno.usou_dados = True
    resultado = {'compras': compras[:MAX_COMPRAS]}
    if not compras:
        resultado['observacao'] = 'Nenhuma parcela em aberto.'
    elif len(compras) > MAX_COMPRAS:
        resultado['observacao'] = f'Há mais compras além destas {MAX_COMPRAS}; para ver todas, transfira.'
    return resultado


def _gerar_link(turno: Turno, entrada: dict) -> dict:
    from vendas.models import Parcela

    clientes = _clientes_liberados(turno)
    try:
        parcela_id = int(entrada.get('parcela_id'))
    except (TypeError, ValueError) as erro:
        raise ErroFerramenta('parcela_id inválido: use um parcela_id de consultar_parcelas.') from erro
    parcela = (Parcela.objects.select_related('pagamento')
               .filter(pk=parcela_id, pagamento__in=pagamentos.pagamentos_em_aberto(clientes)).first())
    if parcela is None:
        raise ErroFerramenta('Parcela não encontrada entre as compras deste cliente.')
    if parcela.pago:
        raise ErroFerramenta('Essa parcela já está paga.')
    try:
        link = link_da_parcela(parcela)
    except LinkIndisponivel as erro:
        raise ErroFerramenta(f'{erro} Transfira para um atendente enviar o pagamento.') from erro
    turno.usou_dados = True
    return {'parcela': parcela.numero_parcela, 'valor': _reais(parcela.valor_restante), **link}


def _transferir(turno: Turno, entrada: dict) -> dict:
    from crm.services.conversas import transferir

    if turno.transferiu:
        return {'observacao': 'A conversa já foi passada para a equipe. Não chame a transferência de novo.'}
    motivo = str(entrada.get('motivo') or '').strip()[:MAX_MOTIVO] or 'Sem detalhes.'
    if not transferir(turno.conversa, f'Assistente de IA transferiu: {motivo}'):
        return {'observacao': 'A conversa já está com a equipe. Encerre sem escrever nada para o cliente.'}
    turno.transferiu = True
    return {'ok': True, 'instrucao': 'Avise o cliente, em uma frase, que um atendente vai continuar por aqui.'}


EXECUTORES = {
    'identificar_cliente': _identificar,
    'consultar_parcelas': _consultar,
    'gerar_link_pagamento': _gerar_link,
    'transferir_para_atendente': _transferir,
}


def executar(turno: Turno, nome: str, entrada: dict) -> dict:
    executor = EXECUTORES.get(nome)
    if executor is None:
        raise ErroFerramenta(f'Ferramenta desconhecida: {nome}.')
    return executor(turno, entrada if isinstance(entrada, dict) else {})
