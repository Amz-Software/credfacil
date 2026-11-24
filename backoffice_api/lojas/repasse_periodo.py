"""Um período do calendário de repasses (6/16/26) de uma loja: vendas, total e baixa direta como pago."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet, Sum

from financeiro.models import Repasse
from vendas.models import Loja, Venda
from vendas.services.erros import ErroDeNegocio
from vendas.services.lojas import PeriodoRepasse, periodo_do_dia

from .servicos import data_do_repasse

OBSERVACAO_BAIXA = 'Marcado como pago pelo calendário de repasses (valor total do período).'


@dataclass(frozen=True)
class ResumoDoPeriodo:
    loja: Loja
    periodo: PeriodoRepasse
    vendas: list
    total: Decimal
    repasses: list


def vendas_do_periodo(loja: Loja, periodo: PeriodoRepasse) -> QuerySet:
    """Mesmo recorte de `status_repasses_por_loja`: vendas ativas com data local no período."""
    return Venda.objects.filter(
        loja=loja, is_deleted=False,
        data_venda__date__gte=periodo.inicio, data_venda__date__lte=periodo.fim,
    )


def repasses_do_periodo(loja: Loja, dia: date) -> QuerySet:
    return Repasse.objects.filter(loja=loja, data__date=dia)


def resumo_do_periodo(loja: Loja, dia: date) -> ResumoDoPeriodo:
    periodo = periodo_do_dia(dia)
    vendas = list(
        vendas_do_periodo(loja, periodo)
        .select_related('cliente')
        .prefetch_related('itens_venda__produto')
        .order_by('data_venda', 'id')
    )
    total = sum((v.repasse_logista or Decimal('0') for v in vendas), Decimal('0.00'))
    repasses = list(repasses_do_periodo(loja, dia).select_related('criado_por').order_by('data', 'id'))
    return ResumoDoPeriodo(loja=loja, periodo=periodo, vendas=vendas, total=total, repasses=repasses)


def pagar_periodo(loja: Loja, dia: date, usuario, hoje: date | None = None) -> Repasse:
    """Cria o repasse do período já pago, com o valor total das vendas.

    A loja é travada na transação para que dois cliques simultâneos não
    criem dois repasses para o mesmo período.
    """
    hoje = hoje or date.today()
    periodo = periodo_do_dia(dia)
    if periodo.fim >= hoje:
        raise ErroDeNegocio('O período deste repasse ainda não fechou.')
    with transaction.atomic():
        Loja.objects.select_for_update().filter(pk=loja.pk).first()
        if repasses_do_periodo(loja, dia).exists():
            raise ErroDeNegocio('Este período já tem repasse lançado.')
        total = vendas_do_periodo(loja, periodo).aggregate(total=Sum('repasse_logista'))['total'] or Decimal('0')
        if total <= 0:
            raise ErroDeNegocio('Este período não tem valor de repasse.')
        return Repasse.objects.create(
            loja=loja, valor=total, data=data_do_repasse(dia), status='pago',
            observacao=OBSERVACAO_BAIXA, criado_por=usuario, atualizado_por=usuario,
        )
