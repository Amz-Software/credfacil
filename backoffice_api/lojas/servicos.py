"""Leitura do calendário de repasses, KPIs da loja e regras de status de repasse.

O calendário usa `vendas.services.lojas.status_repasses_por_loja` com
`marcar_parciais=False`: a API nunca grava nada em GET.
"""
from datetime import date, datetime, time
from decimal import Decimal

from django.db.models import Count, QuerySet, Sum
from django.utils import timezone

from financeiro.models import Repasse
from vendas.models import Loja, Venda
from vendas.services.erros import ErroDeNegocio
from vendas.services.lojas import LIMITE_MESES_REPASSE, status_repasses_por_loja

STATUS_REPASSE = ('pendente', 'pago', 'cancelado', 'parcial')
ROTULOS_STATUS_REPASSE = {'pendente': 'Pendente', 'pago': 'Pago', 'cancelado': 'Cancelado', 'parcial': 'Parcial'}
STATUS_CRIACAO = ('pendente', 'pago', 'cancelado')
# Status finais não mudam; 'parcial' (valor lançado menor que o devido) segue a regra do pendente.
TRANSICOES = {'pendente': {'pago', 'cancelado'}, 'parcial': {'pago', 'cancelado'}, 'pago': set(), 'cancelado': set()}
STATUS_FINAIS = ('pago', 'cancelado')
MESES_DETALHE = 1


def periodo_para_json(periodo: dict, hoje: date) -> dict:
    return {
        'data': periodo['data'],
        'inicio_periodo': periodo['inicio_periodo'],
        'fim_periodo': periodo['fim_periodo'],
        'qtd_vendas': periodo['qtd_vendas'],
        'valor_total_repasse': _dinheiro(periodo['valor_total_repasse']),
        'feito': periodo['feito'],
        'parcial': periodo.get('parcial', False),
        'atrasado': not periodo['feito'] and periodo['data'] < hoje,
    }


def calendario_por_loja(lojas, meses_atras: int = 0, hoje: date | None = None) -> dict:
    """{loja_id: (periodos_json, atrasados)} sem efeitos colaterais."""
    hoje = hoje or date.today()
    meses = max(0, min(meses_atras, LIMITE_MESES_REPASSE))
    status = status_repasses_por_loja(list(lojas), meses_atras=meses, hoje=hoje, marcar_parciais=False)
    return {
        loja_id: ([periodo_para_json(p, hoje) for p in periodos], atrasados)
        for loja_id, (periodos, atrasados) in status.items()
    }


def situacao_repasse(periodos: list, atrasados: int) -> str:
    """Selo da lista de lojas: pendente, em dia ou sem dados (tela Django)."""
    if not periodos:
        return 'sem_dados'
    return 'pendente' if atrasados > 0 else 'em_dia'


def calendario_do_detalhe(loja: Loja, data_inicio: date | None, data_fim: date | None) -> dict:
    """Calendário do mês anterior e atual, recortado pelo período (como a tela Django)."""
    hoje = date.today()
    periodos, _ = calendario_por_loja([loja], meses_atras=MESES_DETALHE, hoje=hoje)[loja.id]
    periodos = [
        p for p in periodos
        if (data_inicio is None or p['data'] >= data_inicio) and (data_fim is None or p['data'] <= data_fim)
    ]
    return {'periodos': periodos, 'atrasados': sum(1 for p in periodos if p['atrasado'])}


def vendas_do_periodo(loja: Loja, data_inicio: date | None, data_fim: date | None) -> QuerySet:
    vendas = Venda.objects.filter(loja=loja, is_deleted=False)
    if data_inicio:
        vendas = vendas.filter(data_venda__date__gte=data_inicio)
    if data_fim:
        vendas = vendas.filter(data_venda__date__lte=data_fim)
    return vendas


def _dinheiro(valor) -> str:
    return f'{Decimal(valor or 0):.2f}'


def kpis_da_loja(loja: Loja, data_inicio: date | None, data_fim: date | None) -> dict:
    vendas = vendas_do_periodo(loja, data_inicio, data_fim)
    return {
        'qtd_vendas': vendas.aggregate(qtd=Count('id'))['qtd'] or 0,
        'valor_total': _dinheiro(vendas.aggregate(valor=Sum('pagamentos__valor'))['valor']),
        'valor_repasse': _dinheiro(loja.calcular_valor_repasse(data_inicio, data_fim)),
    }


def data_do_repasse(dia: date) -> datetime:
    """`Repasse.data` é DateTimeField: meia-noite no fuso local, como o formulário Django."""
    return timezone.make_aware(datetime.combine(dia, time.min))


def validar_mudanca_de_status(repasse: Repasse, novo_status: str | None) -> None:
    if novo_status is None or novo_status == repasse.status:
        return
    if novo_status not in TRANSICOES.get(repasse.status, set()):
        raise ErroDeNegocio(
            f'Repasse {ROTULOS_STATUS_REPASSE.get(repasse.status, repasse.status).lower()} '
            f'não pode passar para {ROTULOS_STATUS_REPASSE.get(novo_status, novo_status).lower()}.'
        )


def validar_edicao_de_valores(repasse: Repasse, dados: dict) -> None:
    if repasse.status in STATUS_FINAIS and ({'valor', 'data'} & set(dados)):
        raise ErroDeNegocio('Repasse pago ou cancelado não pode ter valor ou data alterados.')
