"""Cálculos de leitura de contas a receber, sem consultas extras.

Trabalham sobre as parcelas já carregadas (prefetch) para evitar N+1 e
espelham os métodos de `Pagamento` usados pela tela Django de contas a receber
(`valor_atrasado`, `valor_a_vencer`, `proximo_vencimento`...).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .constantes import (
    PARCELA_ATRASADA,
    PARCELA_EM_DIA,
    PARCELA_PAGA_PARCIALMENTE,
    ROTULOS_ESTADO,
)

ZERO = Decimal('0.00')
# Situações que, ligadas, definem o estado exibido (na ordem de prioridade da tela).
SITUACOES_QUE_DEFINEM_ESTADO = ('desativado', 'devolucao', 'bloqueado', 'sem_contato', 'mais_prazo')


@dataclass(frozen=True)
class FlagsStatus:
    """Os mesmos indicadores de `PagamentoQuerySet.with_status_flags`."""

    todas_parcelas_pagas: bool
    pago_dentro_prazo: bool
    com_parcela_atrasada: bool
    com_pagamento_pendente: bool


def flags_calculadas(parcelas: list, hoje: date) -> FlagsStatus:
    """Mesma regra de `with_status_flags`, calculada em memória (lista e detalhe)."""
    total = len(parcelas)
    pagas = sum(1 for p in parcelas if p.pago)
    pagas_no_prazo = sum(
        1 for p in parcelas
        if p.pago and p.data_pagamento is not None and p.data_pagamento <= p.data_vencimento
    )
    atrasadas = sum(1 for p in parcelas if not p.pago and p.data_vencimento < hoje)
    return FlagsStatus(
        todas_parcelas_pagas=pagas == total,
        pago_dentro_prazo=pagas_no_prazo == total,
        com_parcela_atrasada=atrasadas > 0,
        com_pagamento_pendente=pagas < total and atrasadas == 0,
    )


def estado_da_conta(pagamento, flags: FlagsStatus) -> str:
    """Estado exibido: a primeira condição verdadeira, na ordem da tela Django."""
    for situacao in SITUACOES_QUE_DEFINEM_ESTADO:
        if getattr(pagamento, situacao):
            return situacao
    if flags.com_parcela_atrasada:
        return 'atrasado'
    if flags.com_pagamento_pendente:
        return 'pendente'
    if flags.pago_dentro_prazo:
        return 'pago'
    if flags.todas_parcelas_pagas:
        return 'quitado'
    return 'sem_situacao'


def rotulo_do_estado(estado: str) -> str:
    return ROTULOS_ESTADO.get(estado, ROTULOS_ESTADO['sem_situacao'])


def _soma(valores) -> Decimal:
    return sum(valores, ZERO)


def situacao_da_parcela_em_aberto(parcelas: list, hoje: date) -> str:
    """Primeira parcela em aberto (por vencimento): em dia, atrasada ou paga em parte."""
    em_aberto = sorted((p for p in parcelas if not p.pago), key=lambda p: (p.data_vencimento, p.pk or 0))
    if not em_aberto or em_aberto[0].data_vencimento >= hoje:
        return PARCELA_EM_DIA
    primeira = em_aberto[0]
    return PARCELA_PAGA_PARCIALMENTE if primeira.valor_restante < primeira.valor else PARCELA_ATRASADA


def _ultima_parcela_paga(parcelas: list):
    pagas = [p for p in parcelas if p.pago]
    if not pagas:
        return None
    return max(pagas, key=lambda p: (p.data_pagamento is not None, p.data_pagamento or date.min, p.pk or 0))


def valores_da_conta(pagamento, parcelas: list, hoje: date) -> dict:
    """Colunas de valores da lista (atrasado, último pago, a vencer, total, progresso)."""
    em_aberto = [p for p in parcelas if not p.pago]
    vencidas = [p for p in em_aberto if p.data_vencimento < hoje]
    a_vencer = [p for p in em_aberto if p.data_vencimento >= hoje]
    devolucao = pagamento.devolucao
    ultima_paga = _ultima_parcela_paga(parcelas)
    return {
        'valor_atrasado': ZERO if devolucao else _soma(p.valor_restante for p in vencidas),
        'ultimo_vencimento_atrasado': max((p.data_vencimento for p in vencidas), default=None),
        'valor_pago_ultimo': ultima_paga.valor_pago_efetivo if ultima_paga else ZERO,
        'ultimo_pagamento': ultima_paga.data_pagamento if ultima_paga else None,
        'valor_a_vencer': ZERO if devolucao else _soma(p.valor_restante for p in a_vencer),
        'proximo_vencimento': None if devolucao else min((p.data_vencimento for p in a_vencer), default=None),
        'valor_total_parcelas': _soma(p.valor for p in parcelas),
        'valor_quitado': _soma(p.valor_pago_efetivo for p in parcelas if p.pago),
        'parcelas_pagas': sum(1 for p in parcelas if p.pago),
        'parcelas_totais': len(parcelas),
        'situacao_parcela_aberta': situacao_da_parcela_em_aberto(parcelas, hoje),
    }


def totais_do_detalhe(pagamento, parcelas: list) -> dict:
    """Cartões do detalhe: valor total, pago, pendente e progresso das parcelas."""
    total_pago = _soma(p.valor_pago_efetivo for p in parcelas if p.pago)
    return {
        'valor': pagamento.valor,
        'total_pago': total_pago,
        'valor_pendente': pagamento.valor - total_pago,
        'parcelas_pagas': sum(1 for p in parcelas if p.pago),
        'parcelas_totais': len(parcelas),
        'total_valor_original': _soma(p.valor for p in parcelas),
        'total_valor_pago': _soma(p.valor_pago or ZERO for p in parcelas),
        'aguardando_quitacao': sum(1 for p in parcelas if p.pagamento_efetuado and not p.pago),
    }


def tem_parcela_vencida_em_aberto(parcelas: list, hoje: date) -> bool:
    """Pré-requisito do BO: alguma parcela em aberto com vencimento passado."""
    return any(not p.pago and p.data_vencimento < hoje for p in parcelas)
