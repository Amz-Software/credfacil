"""Regras de escrita de contas a receber usadas pela API do backoffice.

Extraídas das telas Django (sem alterá-las):
- situações: `vendas/views/pagamentos.py` (toggle_*_pagamento, toggle_status_pagamento);
- quitação: `vendas/views/pagamentos.py:ConfirmarQuitacaoView.post`;
- desconto, edição e inclusão de parcelas: `financeiro/views.py:ContasAReceberDetailView.post`.

`Pagamento` sempre é salvo com `update_fields`: um `save()` completo dispara
`vendas.signals.criar_ou_atualizar_parcelas`, que apaga e recria as parcelas.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from vendas.models import Pagamento, Parcela, StatusPagamento
from vendas.services.erros import ErroDeNegocio

from .constantes import CHAVES_SITUACAO

CENTAVO = Decimal('0.01')
ZERO = Decimal('0.00')
CAMPOS_RASTREIO = ['modificado_por', 'modificado_em']
CAMPOS_EDITAVEIS_PARCELA = ('valor_pago', 'pago', 'data_pagamento', 'data_vencimento', 'origem_baixa')
MENSAGEM_SEM_QUITACAO = 'Nenhuma parcela aguardando confirmação de quitação.'
MENSAGEM_SEM_PARCELA_ABERTA = 'Nenhuma parcela em aberto para quitar.'


@dataclass(frozen=True)
class Mudanca:
    antes: object
    depois: object

    @property
    def mudou(self) -> bool:
        return self.antes != self.depois


def _novo_valor(atual: bool, ativo: bool | None) -> bool:
    """`ativo` None alterna (como os toggles antigos); True/False define."""
    return (not atual) if ativo is None else bool(ativo)


def alterar_situacao(pagamento: Pagamento, situacao: str, ativo: bool | None, user) -> Mudanca:
    if situacao not in CHAVES_SITUACAO:
        raise ErroDeNegocio('Situação desconhecida.')
    mudanca = Mudanca(getattr(pagamento, situacao), _novo_valor(getattr(pagamento, situacao), ativo))
    if mudanca.mudou:
        setattr(pagamento, situacao, mudanca.depois)
        pagamento.save(user=user, update_fields=[situacao, *CAMPOS_RASTREIO])
    return mudanca


def alterar_status_pagamento(pagamento: Pagamento, status: StatusPagamento, ativo: bool | None) -> Mudanca:
    atual = pagamento.statuses.filter(pk=status.pk).exists()
    mudanca = Mudanca(atual, _novo_valor(atual, ativo))
    if mudanca.mudou:
        if mudanca.depois:
            pagamento.statuses.add(status)
        else:
            pagamento.statuses.remove(status)
    return mudanca


def alterar_desconto(pagamento: Pagamento, porcentagem: Decimal, user) -> Mudanca:
    mudanca = Mudanca(pagamento.porcentagem_desconto, porcentagem)
    if mudanca.mudou:
        pagamento.porcentagem_desconto = porcentagem
        pagamento.save(user=user, update_fields=['porcentagem_desconto', *CAMPOS_RASTREIO])
    return mudanca


def _salvar_parcela(parcela: Parcela, campos: list[str], user) -> None:
    parcela.save(user=user, update_fields=[*campos, *CAMPOS_RASTREIO])


def _parcelas_a_quitar(pagamento: Pagamento, forcar: bool) -> list[Parcela]:
    """Informadas pelo cliente; com `forcar` (só administrador), todas as em aberto."""
    filtro = {'pagamento': pagamento, 'pago': False}
    if not forcar:
        filtro['pagamento_efetuado'] = True
    return list(Parcela.objects.select_for_update().filter(**filtro).order_by('numero_parcela', 'id'))


def confirmar_quitacao(pagamento: Pagamento, user, forcar: bool = False) -> dict | None:
    """Aplica o desconto do pagamento às parcelas a quitar e as marca como pagas.

    Distribui o total com desconto proporcionalmente; a última parcela absorve o
    arredondamento (mesmo cálculo da tela Django).

    Idempotente: se a conta já está quitada e não sobrou parcela a quitar, devolve
    None sem erro. Cobre a repetição depois de uma resposta que não chegou à tela
    (timeout do navegador com a quitação já gravada no servidor).
    """
    with transaction.atomic():
        # Trava o pagamento: duas confirmações simultâneas não quitam duas vezes.
        quitado = Pagamento.objects.select_for_update().values_list('quitado', flat=True).get(pk=pagamento.pk)
        parcelas = _parcelas_a_quitar(pagamento, forcar)
        if not parcelas and quitado:
            return None
        if not parcelas:
            raise ErroDeNegocio(MENSAGEM_SEM_PARCELA_ABERTA if forcar else MENSAGEM_SEM_QUITACAO)
        total_original = sum((p.valor for p in parcelas), ZERO)
        desconto = pagamento.porcentagem_desconto or ZERO
        valor_desconto = (total_original * desconto / Decimal('100')).quantize(CENTAVO)
        total_com_desconto = (total_original - valor_desconto).quantize(CENTAVO)
        proporcao = total_com_desconto / total_original if total_original > 0 else Decimal('1')
        hoje = timezone.localdate()
        ajustes = []
        soma_parcial = ZERO
        for indice, parcela in enumerate(parcelas):
            ultima = indice == len(parcelas) - 1
            novo_valor = (total_com_desconto - soma_parcial) if ultima else (parcela.valor * proporcao).quantize(CENTAVO)
            ajustes.append({'parcela_id': parcela.pk, 'numero': parcela.numero_parcela,
                            'valor_antes': str(parcela.valor), 'valor_depois': str(novo_valor)})
            soma_parcial += novo_valor
            parcela.valor = novo_valor
            parcela.pago = True
            parcela.data_pagamento = hoje
            _salvar_parcela(parcela, ['valor', 'pago', 'data_pagamento'], user)
        pagamento.quitado = True
        pagamento.save(user=user, update_fields=['quitado', *CAMPOS_RASTREIO])
    return {
        'parcelas_quitadas': len(parcelas),
        'total_original': str(total_original),
        'porcentagem_desconto': str(desconto),
        'total_com_desconto': str(total_com_desconto),
        'sem_informe_do_cliente': forcar,
        'ajustes': ajustes,
    }


def editar_parcela(parcela: Parcela, dados: dict, user) -> dict:
    """Grava os campos editáveis que mudaram; devolve {campo: Mudanca}."""
    mudancas = {
        campo: Mudanca(getattr(parcela, campo), valor)
        for campo, valor in dados.items()
        if campo in CAMPOS_EDITAVEIS_PARCELA
    }
    mudancas = {campo: m for campo, m in mudancas.items() if m.mudou}
    if mudancas:
        for campo, mudanca in mudancas.items():
            setattr(parcela, campo, mudanca.depois)
        _salvar_parcela(parcela, list(mudancas), user)
    return mudancas


def _distribuir(saldo: Decimal, quantidade: int) -> list[Decimal]:
    """Divide o saldo em partes de centavos; a última leva a diferença do arredondamento."""
    base = (saldo / Decimal(quantidade)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    diferenca = (saldo - base * quantidade).quantize(CENTAVO)
    return [base] * (quantidade - 1) + [base + diferenca]


def _vencimentos(ultimo: date | None, pedidos: list[date | None]) -> list[date]:
    """Datas pedidas; as omitidas ficam um mês depois da anterior (como a tela)."""
    datas = []
    for pedido in pedidos:
        if pedido is None:
            if ultimo is None:
                raise ErroDeNegocio('Informe a data de vencimento: o pagamento não tem parcelas.')
            pedido = ultimo + relativedelta(months=1)
        datas.append(pedido)
        ultimo = pedido
    return datas


def adicionar_parcelas(pagamento: Pagamento, pedidos: list[date | None], user) -> dict:
    """Inclui parcelas no fim e redistribui o saldo (valor − total pago) entre as pendentes."""
    with transaction.atomic():
        existentes = list(
            Parcela.objects.select_for_update().filter(pagamento=pagamento).order_by('numero_parcela', 'id')
        )
        ultima = existentes[-1] if existentes else None
        vencimentos = _vencimentos(ultima.data_vencimento if ultima else None, pedidos)
        proximo_numero = (Parcela.objects.filter(pagamento=pagamento).aggregate(m=Max('numero_parcela'))['m'] or 0) + 1
        novas = [
            Parcela(pagamento=pagamento, loja=pagamento.loja, numero_parcela=proximo_numero + i,
                    valor=ZERO, valor_pago=ZERO, data_vencimento=vencimento,
                    pago=False, pagamento_efetuado=False, data_pagamento=None)
            for i, vencimento in enumerate(vencimentos)
        ]
        pago_total = sum((p.valor_pago_efetivo for p in existentes if p.pago), ZERO)
        saldo = max(Decimal(pagamento.valor) - pago_total, ZERO)
        pendentes = [p for p in existentes if not p.pago] + novas
        redistribuidas = []
        for parcela, valor in zip(pendentes, _distribuir(saldo, len(pendentes))):
            if parcela.pk is not None and parcela.valor != valor:
                redistribuidas.append({'parcela_id': parcela.pk, 'numero': parcela.numero_parcela,
                                       'valor_antes': str(parcela.valor), 'valor_depois': str(valor)})
                parcela.valor = valor
                _salvar_parcela(parcela, ['valor'], user)
            elif parcela.pk is None:
                parcela.valor = valor
        for parcela in novas:
            parcela.save(user=user)
    return {
        'novas': [{'parcela_id': p.pk, 'numero': p.numero_parcela,
                   'data_vencimento': p.data_vencimento.isoformat(), 'valor': str(p.valor)} for p in novas],
        'redistribuidas': redistribuidas,
        'saldo_distribuido': str(saldo),
    }
