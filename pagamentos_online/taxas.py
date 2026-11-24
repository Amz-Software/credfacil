"""Taxa repassada ao cliente por forma de pagamento. Pix não tem taxa.

Cada função devolve `(total, taxa)`, sempre em centavos.
"""
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENTAVO = Decimal('0.01')
CEM = Decimal('100')


def _centavos(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def total_pix(valor: Decimal) -> tuple[Decimal, Decimal]:
    return _centavos(valor), Decimal('0.00')


def total_boleto(valor: Decimal, tarifa: Decimal) -> tuple[Decimal, Decimal]:
    taxa = _centavos(tarifa)
    return _centavos(valor) + taxa, taxa


def total_cartao(valor: Decimal, percentual: Decimal) -> tuple[Decimal, Decimal]:
    """Calcula "por dentro": descontada a taxa do total, sobra o valor cheio da parcela."""
    percentual = Decimal(percentual)
    if not Decimal('0') <= percentual < CEM:
        raise ValueError('Percentual da taxa do cartão deve estar entre 0 e 100.')
    base = _centavos(valor)
    total = (base / (1 - percentual / CEM)).quantize(CENTAVO, rounding=ROUND_CEILING)
    return total, total - base
