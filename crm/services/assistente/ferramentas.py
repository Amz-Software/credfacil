"""Ferramentas que o modelo pode pedir. Toda regra de acesso é conferida aqui, não no prompt.

A lista DEFINICOES tem ordem e texto fixos: ela entra no prefixo cacheado do prompt.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, EncaminhamentoIA
from crm.services import contatos, expediente, pagamentos
from crm.services.assistente import anexos, identidade
from crm.services.links_pagamento import LinkIndisponivel, link_da_parcela

MAX_COMPRAS = 5
MAX_PARCELAS_POR_COMPRA = 12
MAX_MOTIVO = 1000
MAX_FRACAO_DESCONTO = Decimal('0.5')  # antecipação nunca passa de 50% da parcela
CENTAVO = Decimal('0.01')
Assunto = EncaminhamentoIA.Assunto

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
        'name': 'simular_quitacao',
        'description': (
            'Valor para o cliente identificado quitar de uma vez tudo o que falta de cada compra, com o desconto '
            'de quitação do plano. É o mesmo valor da opção "quitação total" da página de pagamento (link).'
        ),
        'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    },
    {
        'name': 'simular_antecipacao',
        'description': (
            'Calcula o desconto estimado para o cliente identificado adiantar parcelas a vencer (regra da '
            'empresa por dia antecipado). Só informa: quem fecha a antecipação é a equipe.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'parcela_ids': {
                    'type': 'array', 'items': {'type': 'integer'}, 'minItems': 1, 'maxItems': 12,
                    'description': 'parcela_id (de consultar_parcelas) das parcelas que o cliente quer adiantar.',
                },
            },
            'required': ['parcela_ids'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'registrar_comprovante',
        'description': (
            'Anexa à parcela o comprovante (imagem ou PDF) que o cliente identificado acabou de mandar nesta '
            'conversa e marca a parcela como "pagamento informado" para a equipe conferir. Use só depois de '
            'ver que o arquivo parece mesmo um comprovante de pagamento.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {'parcela_id': {'type': 'integer', 'description': 'parcela_id da parcela paga.'}},
            'required': ['parcela_id'],
            'additionalProperties': False,
        },
    },
    {
        'name': 'transferir_para_atendente',
        'description': (
            'Passa a conversa para a equipe humana. Depois, avise o cliente em uma frase curta que um atendente '
            'vai continuar por aqui (fora do horário comercial, diga quando a equipe volta). Use uma vez só.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'assunto': {'type': 'string', 'enum': list(Assunto.values),
                            'description': 'Assunto principal do atendimento.'},
                'motivo': {
                    'type': 'string',
                    'description': 'Nota interna para a equipe: quem é o cliente, o que pediu e o que ficou pendente.',
                },
            },
            'required': ['assunto', 'motivo'],
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


def _loja(venda) -> dict:
    loja = venda.loja
    if loja is None:
        return {}
    return {'nome': loja.nome, 'endereco': loja.endereco or ''}


def _compra(pagamento, hoje: date) -> dict | None:
    abertas = sorted((p for p in pagamento.parcelas_pagamento.all() if not p.pago),
                     key=lambda p: p.numero_parcela)
    if not abertas:
        return None
    atrasadas = [p for p in abertas if p.data_vencimento < hoje and not p.pagamento_efetuado]
    return {
        'produto': pagamentos._produto(pagamento.venda),
        'aparelho_bloqueado': bool(pagamento.bloqueado),
        'loja': _loja(pagamento.venda),
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
    diferente = any([contatos.registrar_numero_do_atendimento(c, turno.conversa.telefone) for c in clientes])
    nome = (clientes[0].nome or '').split()
    return {'identificado': True, 'primeiro_nome': nome[0].capitalize() if nome else '',
            'numero_diferente_do_cadastro': diferente}


def _consultar(turno: Turno, entrada: dict) -> dict:
    hoje = timezone.localdate()
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


def _parcelas_do_cliente(turno: Turno, ids) -> list:
    """Parcelas em aberto das compras do cliente identificado (nunca de outra pessoa)."""
    from vendas.models import Parcela

    clientes = _clientes_liberados(turno)
    try:
        ids = [int(i) for i in ids]
    except (TypeError, ValueError) as erro:
        raise ErroFerramenta('parcela_id inválido: use um parcela_id de consultar_parcelas.') from erro
    parcelas = list(Parcela.objects.select_related('pagamento')
                    .filter(pk__in=ids, pagamento__in=pagamentos.pagamentos_em_aberto(clientes))
                    .order_by('data_vencimento'))
    if len(parcelas) != len(set(ids)):
        raise ErroFerramenta('Parcela não encontrada entre as compras deste cliente.')
    if any(p.pago for p in parcelas):
        raise ErroFerramenta('Essa parcela já está paga.')
    return parcelas


def _gerar_link(turno: Turno, entrada: dict) -> dict:
    parcela = _parcelas_do_cliente(turno, [entrada.get('parcela_id')])[0]
    try:
        link = link_da_parcela(parcela)
    except LinkIndisponivel as erro:
        raise ErroFerramenta(f'{erro} Transfira para um atendente enviar o pagamento.') from erro
    turno.usou_dados = True
    return {'parcela': parcela.numero_parcela, 'valor': _reais(parcela.valor_restante), **link}


def _desconto(parcela, percentual_dia: Decimal, hoje: date) -> tuple[int, Decimal]:
    dias = (parcela.data_vencimento - hoje).days
    if dias <= 0:
        return 0, Decimal('0')
    fracao = min(percentual_dia / 100 * dias, MAX_FRACAO_DESCONTO)
    return dias, (parcela.valor_restante * fracao).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _antecipar(turno: Turno, entrada: dict) -> dict:
    percentual = ConfiguracaoCRM.obter().antecipacao_percentual_dia
    if not percentual:
        raise ErroFerramenta('Não há regra de antecipação cadastrada. Diga que a equipe calcula o desconto e '
                             'transfira (assunto ANTECIPACAO).')
    ids = entrada.get('parcela_ids') or []
    if not ids:
        raise ErroFerramenta('Informe ao menos um parcela_id de consultar_parcelas.')
    parcelas = _parcelas_do_cliente(turno, ids)
    hoje = timezone.localdate()
    itens, total, total_desconto = [], Decimal('0'), Decimal('0')
    for parcela in parcelas:
        dias, desconto = _desconto(parcela, percentual, hoje)
        total += parcela.valor_restante
        total_desconto += desconto
        itens.append({'numero': parcela.numero_parcela, 'vencimento': parcela.data_vencimento.strftime('%d/%m/%Y'),
                      'valor': _reais(parcela.valor_restante), 'dias_antecipados': dias,
                      'desconto': _reais(desconto), 'valor_com_desconto': _reais(parcela.valor_restante - desconto)})
    turno.usou_dados = True
    return {
        'parcelas': itens, 'total_sem_desconto': _reais(total), 'desconto_total': _reais(total_desconto),
        'total_com_desconto': _reais(total - total_desconto),
        'observacao': ('Valor estimado para pagamento hoje; parcela vencida ou que vence hoje não tem desconto. '
                       'O link de pagamento cobra o valor cheio: se o cliente quiser antecipar, transfira '
                       '(assunto ANTECIPACAO) para a equipe confirmar e enviar o pagamento com desconto.'),
    }


def _quitacao_da_compra(pagamento) -> dict | None:
    """Mesma conta da página pública de pagamento (vendas/views/publico.py): soma o valor das parcelas
    em aberto e tira a porcentagem_desconto do plano."""
    abertas = [p for p in pagamento.parcelas_pagamento.all() if not p.pago]
    if not abertas:
        return None
    total = sum((p.valor for p in abertas), Decimal('0'))
    percentual = pagamento.porcentagem_desconto or Decimal('0')
    desconto = (total * percentual / 100).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return {
        'produto': pagamentos._produto(pagamento.venda), 'parcelas_em_aberto': len(abertas),
        'total_em_aberto': _reais(total), 'percentual_desconto': f'{percentual.normalize():f}%',
        'desconto': _reais(desconto), 'valor_para_quitar': _reais(total - desconto),
        'link': pagamentos._link(pagamento.token_publico),
    }


def _quitar(turno: Turno, entrada: dict) -> dict:
    compras = []
    for pagamento in pagamentos.pagamentos_em_aberto(_clientes_liberados(turno)):
        compra = _quitacao_da_compra(pagamento)
        if compra:
            compras.append(compra)
        if len(compras) >= MAX_COMPRAS:
            break
    turno.usou_dados = True
    if not compras:
        return {'observacao': 'Nenhuma parcela em aberto: não há o que quitar.'}
    return {
        'compras': compras,
        'observacao': ('Informe o valor para quitar e mande o link: na página há a opção "quitação total" com o '
                       'PIX desse valor. Com 0% não há desconto de quitação nesse plano. Depois do pagamento, peça '
                       'o comprovante e transfira (QUITACAO) para a equipe confirmar a quitação.'),
    }


def _comprovante(turno: Turno, entrada: dict) -> dict:
    parcela = _parcelas_do_cliente(turno, [entrada.get('parcela_id')])[0]
    if parcela.pagamento_efetuado:
        raise ErroFerramenta('Essa parcela já tem pagamento informado, aguardando a equipe conferir.')
    try:
        anexos.registrar_comprovante(turno.conversa, parcela)
    except anexos.AnexoIndisponivel as erro:
        raise ErroFerramenta(str(erro)) from erro
    turno.usou_dados = True
    return {'ok': True, 'parcela': parcela.numero_parcela,
            'instrucao': ('Agradeça e diga que a equipe confere o pagamento e dá baixa; não diga que já está '
                          'pago. Se o cliente pediu desbloqueio do aparelho, transfira (assunto DESBLOQUEIO).')}


def _transferir(turno: Turno, entrada: dict) -> dict:
    from crm.services.conversas import transferir

    if turno.transferiu:
        return {'observacao': 'A conversa já foi passada para a equipe. Não chame a transferência de novo.'}
    assunto = entrada.get('assunto') if entrada.get('assunto') in Assunto.values else Assunto.OUTRO
    motivo = str(entrada.get('motivo') or '').strip()[:MAX_MOTIVO] or 'Sem detalhes.'
    rotulo = Assunto(assunto).label
    if not transferir(turno.conversa, f'Assistente de IA transferiu ({rotulo}): {motivo}'):
        return {'observacao': 'A conversa já está com a equipe. Encerre sem escrever nada para o cliente.'}
    turno.transferiu = True
    aberto = expediente.aberto()
    EncaminhamentoIA.objects.create(conversa=turno.conversa, assunto=assunto, fora_do_horario=not aberto)
    if aberto:
        return {'ok': True, 'instrucao': 'Avise o cliente, em uma frase, que um atendente vai continuar por aqui.'}
    return {'ok': True, 'fora_do_horario': True, 'mensagem_fora_do_horario': ConfiguracaoCRM.obter().mensagem_fora_horario,
            'instrucao': ('Estamos fora do horário comercial: avise com naturalidade, usando a mensagem de fora do '
                          'horário como base, que a equipe responde no próximo atendimento.')}


EXECUTORES = {
    'identificar_cliente': _identificar,
    'consultar_parcelas': _consultar,
    'gerar_link_pagamento': _gerar_link,
    'simular_quitacao': _quitar,
    'simular_antecipacao': _antecipar,
    'registrar_comprovante': _comprovante,
    'transferir_para_atendente': _transferir,
}


def executar(turno: Turno, nome: str, entrada: dict) -> dict:
    executor = EXECUTORES.get(nome)
    if executor is None:
        raise ErroFerramenta(f'Ferramenta desconhecida: {nome}.')
    return executor(turno, entrada if isinstance(entrada, dict) else {})
