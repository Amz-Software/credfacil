"""Peças comuns dos relatórios: escopo de lojas, intervalo de datas e somas por subconsulta."""
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, DecimalField, F, OuterRef, Q, QuerySet, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

DINHEIRO = DecimalField(max_digits=14, decimal_places=2)
ZERO = Value(Decimal('0'), output_field=DINHEIRO)
ROTULOS_STATUS_ANALISE = {'A': 'Aprovada', 'R': 'Reprovada', 'EA': 'Em Análise', 'C': 'Cancelada'}
STATUS_DESCONHECIDO = 'Desconhecido'


@dataclass(frozen=True)
class EscopoRelatorio:
    """Restringe consultas às lojas escolhidas no filtro ou, sem escolha, ao escopo da requisição."""

    lojas_escolhidas: tuple
    aplicar_escopo: Callable[[QuerySet, str], QuerySet]

    def aplicar(self, queryset: QuerySet, campo: str) -> QuerySet:
        if self.lojas_escolhidas:
            return queryset.filter(**{f'{campo}__in': [loja.pk for loja in self.lojas_escolhidas]})
        return self.aplicar_escopo(queryset, campo)


def inicio_do_dia(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


def filtro_periodo(campo: str, inicio: date | None, fim: date | None) -> Q:
    """[início 00:00, fim + 1 dia 00:00): a data final é inclusiva."""
    filtro = Q()
    if inicio:
        filtro &= Q(**{f'{campo}__gte': inicio_do_dia(inicio)})
    if fim:
        filtro &= Q(**{f'{campo}__lt': inicio_do_dia(fim + timedelta(days=1))})
    return filtro


def rotulo_status_analise(status: str | None) -> str:
    return ROTULOS_STATUS_ANALISE.get(status or '', STATUS_DESCONHECIDO)


def soma_relacionada(queryset: QuerySet, campo_ligacao: str, campo_soma) -> Coalesce:
    """Soma de `campo_soma` nas linhas de `queryset` ligadas ao registro externo (OuterRef('pk'))."""
    subconsulta = (
        queryset.filter(**{campo_ligacao: OuterRef('pk')})
        .order_by()
        .values(campo_ligacao)
        .annotate(total=Sum(campo_soma, output_field=DINHEIRO))
        .values('total')
    )
    return Coalesce(Subquery(subconsulta, output_field=DINHEIRO), ZERO)


def valor_restante():
    """Mesma regra de `Parcela.valor_restante`: (valor − desconto) − valor pago."""
    return F('valor') - Coalesce(F('desconto'), ZERO) - Coalesce(F('valor_pago'), ZERO)


def valor_pago_efetivo():
    """Mesma regra de `Parcela.valor_pago_efetivo`: valor pago, se preenchido e diferente de zero; senão o valor."""
    return Case(
        When(Q(valor_pago__isnull=False) & ~Q(valor_pago=0), then=F('valor_pago')),
        default=F('valor'),
        output_field=DINHEIRO,
    )


def soma(valores) -> Decimal:
    return sum((v or Decimal(0) for v in valores), Decimal(0))


def filtrar_comodato(queryset: QuerySet, filtros: dict, campo: str) -> QuerySet:
    """Filtro "Comodato" (Sim/Não); vazio (None) não filtra."""
    comodato = filtros.get('comodato')
    if comodato is None:
        return queryset
    return queryset.filter(**{campo: comodato})


def separar_comodato(linhas: list, e_comodato: Callable, valor: Callable) -> dict:
    """Quantidade e soma de `valor` das linhas de comodato e das demais (vendas comuns)."""
    comodato = [linha for linha in linhas if e_comodato(linha)]
    demais = [linha for linha in linhas if not e_comodato(linha)]
    return {
        'comodato_quantidade': len(comodato),
        'comodato_valor': soma(valor(linha) for linha in comodato),
        'demais_quantidade': len(demais),
        'demais_valor': soma(valor(linha) for linha in demais),
    }


def sim_nao(valor, sim: str, nao: str) -> str:
    """Como o filtro `yesno` do Django com dois valores (None vira o "não")."""
    return sim if valor else nao
