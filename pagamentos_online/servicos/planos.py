"""O que uma cobrança paga: uma parcela, várias parcelas da mesma compra ou a quitação com desconto.

Os valores sempre vêm das parcelas no banco. Na quitação, o desconto do pagamento (`porcentagem_desconto`)
é distribuído proporcionalmente entre as parcelas em aberto; a última absorve o arredondamento,
como em `backoffice_api/financeiro/servicos.py:confirmar_quitacao`.
"""
from dataclasses import dataclass
from decimal import Decimal

from vendas.models import Pagamento, Parcela
from vendas.services.erros import ErroDeNegocio

from ..models import Cobranca

CENTAVO = Decimal('0.01')
ZERO = Decimal('0.00')
CEM = Decimal('100')
Tipo = Cobranca.Tipo


@dataclass(frozen=True)
class ItemPlano:
    parcela: Parcela
    valor: Decimal
    desconto: Decimal = ZERO


@dataclass(frozen=True)
class Plano:
    tipo: str
    pagamento: Pagamento
    itens: tuple[ItemPlano, ...]

    @property
    def valor(self) -> Decimal:
        return sum((item.valor for item in self.itens), ZERO)

    @property
    def desconto(self) -> Decimal:
        return sum((item.desconto for item in self.itens), ZERO)

    @property
    def total_sem_desconto(self) -> Decimal:
        return self.valor + self.desconto

    @property
    def parcela_ids(self) -> frozenset[int]:
        return frozenset(item.parcela.pk for item in self.itens)

    @property
    def primeira(self) -> Parcela:
        return self.itens[0].parcela


def _restante(parcela: Parcela) -> Decimal:
    return max(parcela.valor_restante, ZERO)


def _em_ordem(parcelas) -> list[Parcela]:
    return sorted(parcelas, key=lambda p: (p.numero_parcela, p.pk))


def _exigir_abertas(parcelas: list[Parcela]) -> None:
    pagas = [p.numero_parcela for p in parcelas if p.pago or _restante(p) <= 0]
    if len(pagas) == 1:
        raise ErroDeNegocio(f'A parcela {pagas[0]} já está paga.' if len(parcelas) > 1 else 'Essa parcela já está paga.')
    if pagas:
        raise ErroDeNegocio(f'As parcelas {juntar(pagas)} já estão pagas.')


def plano_de_parcelas(pagamento: Pagamento, parcelas: list[Parcela]) -> Plano:
    if not parcelas:
        raise ErroDeNegocio('Escolha ao menos uma parcela.')
    if any(p.pagamento_id != pagamento.pk for p in parcelas):
        raise ErroDeNegocio('As parcelas precisam ser da mesma compra.')
    ordenadas = _em_ordem(parcelas)
    _exigir_abertas(ordenadas)
    tipo = Tipo.PARCELA if len(ordenadas) == 1 else Tipo.PARCELAS
    return Plano(tipo, pagamento, tuple(ItemPlano(p, _restante(p)) for p in ordenadas))


def plano_de_quitacao(pagamento: Pagamento, abertas: list[Parcela]) -> Plano:
    """Todas as parcelas em aberto com o desconto do plano."""
    ordenadas = [p for p in _em_ordem(abertas) if not p.pago and _restante(p) > 0]
    if not ordenadas:
        raise ErroDeNegocio('Essa compra não tem parcelas em aberto.')
    total = sum((_restante(p) for p in ordenadas), ZERO)
    porcentagem = pagamento.porcentagem_desconto or ZERO
    com_desconto = (total - (total * porcentagem / CEM)).quantize(CENTAVO)
    itens, soma = [], ZERO
    for indice, parcela in enumerate(ordenadas):
        restante = _restante(parcela)
        ultima = indice == len(ordenadas) - 1
        valor = (com_desconto - soma) if ultima else (restante * com_desconto / total).quantize(CENTAVO)
        soma += valor
        itens.append(ItemPlano(parcela, valor, restante - valor))
    return Plano(Tipo.QUITACAO, pagamento, tuple(itens))


def juntar(numeros: list[int]) -> str:
    textos = [str(n) for n in numeros]
    return textos[0] if len(textos) == 1 else f'{", ".join(textos[:-1])} e {textos[-1]}'


def rotulo(tipo: str, numeros: list[int]) -> str:
    """'Parcela 3', 'Parcelas 3, 4 e 5' ou 'Quitação'."""
    if tipo == Tipo.QUITACAO:
        return 'Quitação'
    return f'Parcela {numeros[0]}' if len(numeros) == 1 else f'Parcelas {juntar(numeros)}'


def rotulo_do_plano(plano: Plano) -> str:
    return rotulo(plano.tipo, [item.parcela.numero_parcela for item in plano.itens])


def rotulo_da_cobranca(cobranca: Cobranca) -> str:
    return rotulo(cobranca.tipo, cobranca.numeros_das_parcelas())
