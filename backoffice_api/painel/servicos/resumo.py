"""Blocos do painel inicial: KPIs da carteira, fila de crédito, inadimplência e atalhos."""
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Count, DecimalField, F, QuerySet, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from vendas.models import AnaliseCreditoCliente, Parcela
from vendas.services.kpis import (
    PARCELAS_CONSIDERADAS_POR_VENDA,
    _dados_grafico,
    contar_por_status,
    resumo_carteira_loja,
)

STATUS_EM_ANALISE = 'EA'
SEGUNDOS_POR_MINUTO = 60
ZERO = Value(Decimal(0), output_field=DecimalField(max_digits=14, decimal_places=2))

# Campos numéricos de `resumo_carteira_loja` (somados quando há mais de uma loja).
CAMPOS_CARTEIRA = (
    'total_vendas_loja', 'total_de_parcelas_geral', 'parcelas_vencidas', 'parcelas_pagas',
    'parcelas_a_vencer', 'total_pagas', 'total_vencidas', 'total_a_vencer', 'total_geral_parcelas',
    'total_desativados_vencidas', 'qtd_desativados_vencidas', 'total_desativados_a_vencer',
    'qtd_desativados_a_vencer', 'total_pagamentos_desativados',
)


def _somar_carteiras(lojas: list, hoje: date) -> dict:
    resumos = [resumo_carteira_loja(loja, hoje=hoje) for loja in lojas]
    return {campo: sum((r[campo] for r in resumos), 0) for campo in CAMPOS_CARTEIRA}


def kpis_carteira(lojas: QuerySet, hoje: date | None = None) -> dict | None:
    """KPIs da página inicial (3 primeiras parcelas IPX de cada venda), somando as lojas do recorte."""
    lista = list(lojas)
    if not lista:
        return None
    soma = _somar_carteiras(lista, hoje or timezone.now().date())
    grafico = json.loads(_dados_grafico(soma, soma))
    return {
        'parcelas_consideradas_por_venda': PARCELAS_CONSIDERADAS_POR_VENDA,
        'total_vendas': soma['total_vendas_loja'],
        'total_parcelas': soma['total_de_parcelas_geral'],
        'valor_total': soma['total_geral_parcelas'],
        'parcelas_pagas': soma['parcelas_pagas'],
        'valor_pago': soma['total_pagas'],
        'parcelas_vencidas': soma['parcelas_vencidas'],
        'valor_vencido': soma['total_vencidas'],
        'parcelas_a_vencer': soma['parcelas_a_vencer'],
        'valor_a_vencer': soma['total_a_vencer'],
        'desativados': {
            'total_pagamentos': soma['total_pagamentos_desativados'],
            'parcelas_vencidas': soma['qtd_desativados_vencidas'],
            'valor_vencido': soma['total_desativados_vencidas'],
            'parcelas_a_vencer': soma['qtd_desativados_a_vencer'],
            'valor_a_vencer': soma['total_desativados_a_vencer'],
        },
        'grafico_balanco': {
            'unidade': 'percentual',
            'rotulos': grafico['labels'],
            'valores': grafico['data'],
        },
    }


def _minutos(inicio: datetime, agora: datetime) -> float:
    return max((agora - inicio).total_seconds(), 0) / SEGUNDOS_POR_MINUTO


def resumo_fila_credito(analises: QuerySet, agora: datetime | None = None) -> dict:
    """Contagem por status e espera (desde a criação) das solicitações em análise."""
    agora = agora or timezone.now()
    contagem = contar_por_status(analises)
    rotulos = dict(AnaliseCreditoCliente.STATUS_CHOICES)
    esperas = [
        _minutos(criado_em, agora)
        for criado_em in analises.filter(status=STATUS_EM_ANALISE).values_list('criado_em', flat=True)
        if criado_em
    ]
    return {
        'por_status': [
            {'status': codigo, 'rotulo': rotulos.get(codigo, codigo), 'total': total}
            for codigo, total in contagem.items()
        ],
        'total': sum(contagem.values()),
        'em_espera': contagem.get(STATUS_EM_ANALISE, 0),
        'tempo_medio_espera_minutos': round(sum(esperas) / len(esperas)) if esperas else None,
        'maior_espera_minutos': round(max(esperas)) if esperas else None,
    }


def parcelas_de_contas_a_receber() -> QuerySet:
    """Parcelas dos pagamentos parcelados (fora do caixa) de vendas ativas e sem devolução."""
    return Parcela.objects.filter(
        pagamento__venda__is_deleted=False,
        pagamento__tipo_pagamento__parcelas=True,
        pagamento__tipo_pagamento__caixa=False,
        pagamento__devolucao=False,
    )


def valor_restante():
    """Mesma regra de `Parcela.valor_restante`: (valor − desconto) − valor pago."""
    return F('valor') - Coalesce(F('desconto'), ZERO) - Coalesce(F('valor_pago'), ZERO)


def resumo_inadimplencia(parcelas: QuerySet, hoje: date | None = None) -> dict:
    """Parcelas em aberto com vencimento passado e quanto falta receber delas."""
    hoje = hoje or timezone.localdate()
    totais = parcelas.filter(pago=False, data_vencimento__lt=hoje).aggregate(
        parcelas_atrasadas=Count('id'),
        valor_em_atraso=Coalesce(Sum(valor_restante(), output_field=ZERO.output_field), ZERO),
        pagamentos_em_atraso=Count('pagamento', distinct=True),
        clientes_inadimplentes=Count('pagamento__venda__cliente', distinct=True),
    )
    return totais


@dataclass(frozen=True)
class Atalho:
    id: str
    titulo: str
    descricao: str
    permissoes: tuple[str, ...]  # basta uma


ATALHOS = (
    Atalho('fila_credito', 'Solicitações de crédito', 'Acompanhe e decida as análises de crédito.', ('vendas.view_cliente',)),
    Atalho('vendas', 'Vendas', 'Visualize as vendas dos clientes.', ('vendas.view_venda',)),
    Atalho('contas_a_receber', 'Contas a receber', 'Parcelas, situações e cobrança.', ('vendas.view_pagamento',)),
    Atalho('produtos', 'Produtos', 'Visualize os produtos disponíveis.', ('produtos.view_produto',)),
    Atalho(
        'relatorios', 'Relatórios', 'Central de relatórios em PDF e Excel.',
        ('vendas.can_generate_report_sale', 'vendas.can_genarate_report_payments'),
    ),
    Atalho('graficos', 'Gráficos', 'Balanço das parcelas por loja e por mês.', ('vendas.can_view_all_dashboard',)),
    Atalho('crm', 'Conversas', 'Atendimento pelo WhatsApp.', ('crm.acessar_crm',)),
)


def atalhos_do_usuario(user) -> list[dict]:
    return [
        {'id': a.id, 'titulo': a.titulo, 'descricao': a.descricao}
        for a in ATALHOS
        if any(user.has_perm(p) for p in a.permissoes)
    ]
