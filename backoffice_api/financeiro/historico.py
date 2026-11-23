"""Linha do tempo de uma conta a receber a partir do `simple_history`.

Junta as versões do `Pagamento` (situações, desconto, quitação, status) e das
suas `Parcela`s, com o que mudou em cada versão. Vale para mudanças feitas pela
API nova e pelas telas Django, que gravam o mesmo histórico.
"""
from datetime import date, datetime
from decimal import Decimal

from vendas.models import Pagamento, Parcela, StatusPagamento

LIMITE_HISTORICO = 50
CAMPOS_IGNORADOS = ['modificado_em', 'modificado_por', 'criado_em', 'criado_por']
TIPOS = {'+': 'criacao', '~': 'alteracao', '-': 'remocao'}


def _valor_json(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def _nomes_dos_status(valor, nomes: dict) -> list[str]:
    """O histórico m2m guarda linhas da tabela intermediária; mostra os nomes."""
    if not isinstance(valor, (list, tuple)):
        return []
    ids = [linha.get('statuspagamento') for linha in valor if isinstance(linha, dict)]
    return sorted(nomes.get(i, str(i)) for i in ids if i is not None)


def _alteracoes(registro, anterior, modelo, nomes_status: dict) -> list[dict]:
    diferenca = registro.diff_against(anterior, excluded_fields=CAMPOS_IGNORADOS)
    alteracoes = []
    for mudanca in diferenca.changes:
        de, para = mudanca.old, mudanca.new
        if mudanca.field == 'statuses':
            de, para = _nomes_dos_status(de, nomes_status), _nomes_dos_status(para, nomes_status)
        alteracoes.append({
            'campo': mudanca.field,
            'rotulo': str(modelo._meta.get_field(mudanca.field).verbose_name),
            'de': _valor_json(de),
            'para': _valor_json(para),
        })
    return alteracoes


def _usuario(registro) -> str | None:
    user = registro.history_user
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def _entradas(registros, modelo, objeto: str, nomes_status: dict) -> list[dict]:
    """Uma entrada por versão; `registros` vem em ordem cronológica por objeto."""
    entradas = []
    anteriores: dict = {}
    for registro in registros:
        anterior = anteriores.get(registro.id)
        anteriores[registro.id] = registro
        tipo = TIPOS.get(registro.history_type, 'alteracao')
        alteracoes = []
        if tipo == 'alteracao' and anterior is not None:
            alteracoes = _alteracoes(registro, anterior, modelo, nomes_status)
            if not alteracoes:
                continue
        entradas.append({
            'data': registro.history_date,
            'usuario': _usuario(registro),
            'objeto': objeto,
            'objeto_id': registro.id,
            'numero_parcela': getattr(registro, 'numero_parcela', None),
            'tipo': tipo,
            'alteracoes': alteracoes,
        })
    return entradas


def historico_do_pagamento(pagamento: Pagamento, limite: int = LIMITE_HISTORICO) -> list[dict]:
    """Versões mais recentes primeiro, no máximo `limite`."""
    nomes_status = dict(StatusPagamento.objects.values_list('id', 'nome'))
    do_pagamento = pagamento.history.select_related('history_user').order_by('history_date', 'history_id')
    das_parcelas = (
        Parcela.history.filter(pagamento_id=pagamento.pk)
        .select_related('history_user')
        .order_by('history_date', 'history_id')
    )
    entradas = (
        _entradas(do_pagamento, Pagamento, 'pagamento', nomes_status)
        + _entradas(das_parcelas, Parcela, 'parcela', nomes_status)
    )
    entradas.sort(key=lambda e: e['data'], reverse=True)
    return entradas[:limite]
