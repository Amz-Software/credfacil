"""Filtros e tags das telas do CRM."""
from datetime import datetime

from django import template
from django.utils import timezone

from crm.telefone import formatar_telefone
from crm.web.filtros import Filtros

register = template.Library()

ESTADO_MODO = {'AUTOMATICO': 'info', 'AGUARDANDO': 'warning', 'HUMANO': 'success'}
ESTADO_SITUACAO = {'ABERTA': 'primary', 'PENDENTE': 'warning', 'RESOLVIDA': 'secondary'}
ICONE_STATUS = {
    'PENDENTE': ('bx bx-time-five', 'Enviando'),
    'ENVIADO': ('bx bx-check', 'Enviada'),
    'ENTREGUE': ('bx bx-check-double', 'Entregue'),
    'LIDO': ('bx bx-check-double text-info', 'Lida'),
    'ERRO': ('bx bx-error-circle text-danger', 'Erro no envio'),
}
ROTULO_ORIGEM = {'ABERTURA': 'Abertura', 'BOAS_VINDAS': 'Boas-vindas', 'PROGRAMADA': 'Programada'}
REACOES_RAPIDAS = ('👍', '❤️', '😂', '😮', '🙏', '✅')
UNIDADES_BYTES = ('B', 'KB', 'MB', 'GB')
BYTES_POR_UNIDADE = 1024


@register.filter
def estado_modo(modo: str) -> str:
    return ESTADO_MODO.get(modo, 'secondary')


@register.filter
def estado_situacao(situacao: str) -> str:
    return ESTADO_SITUACAO.get(situacao, 'secondary')


@register.filter
def icone_status(status: str) -> str:
    return ICONE_STATUS.get(status, ('', ''))[0]


@register.filter
def rotulo_status(status: str) -> str:
    return ICONE_STATUS.get(status, ('', ''))[1]


@register.filter
def rotulo_origem(origem: str) -> str:
    return ROTULO_ORIGEM.get(origem, '')


@register.filter
def telefone(numero: str) -> str:
    return formatar_telefone(numero or '')


@register.filter
def quando(valor: datetime | None) -> str:
    """Hora se for hoje, 'Ontem', ou a data curta."""
    if not valor:
        return ''
    local = timezone.localtime(valor)
    hoje = timezone.localdate()
    if local.date() == hoje:
        return local.strftime('%H:%M')
    if (hoje - local.date()).days == 1:
        return 'Ontem'
    return local.strftime('%d/%m/%y')


@register.filter
def tamanho(num_bytes: int | None) -> str:
    if not num_bytes:
        return ''
    valor = float(num_bytes)
    for unidade in UNIDADES_BYTES:
        if valor < BYTES_POR_UNIDADE or unidade == UNIDADES_BYTES[-1]:
            return f'{valor:.0f} {unidade}' if unidade == 'B' else f'{valor:.1f} {unidade}'.replace('.', ',')
        valor /= BYTES_POR_UNIDADE
    return ''


@register.filter
def duracao(segundos: int | None) -> str:
    if not segundos:
        return ''
    return f'{segundos // 60}:{segundos % 60:02d}'


@register.filter
def chave(dicionario: dict, nome: str):
    return (dicionario or {}).get(nome)


@register.filter
def reais(valor) -> str:
    from crm.services.pagamentos import formatar_reais
    from decimal import Decimal, InvalidOperation

    try:
        return formatar_reais(Decimal(str(valor)))
    except (InvalidOperation, TypeError, ValueError):
        return ''


@register.filter
def data_iso(valor: str) -> str:
    """'2026-11-19' -> '19/11/2026'."""
    partes = (valor or '').split('-')
    return '/'.join(reversed(partes)) if len(partes) == 3 else valor


@register.simple_tag
def filtros_com(filtros: Filtros, **trocas) -> str:
    """Querystring dos filtros atuais com trocas: {% filtros_com filtros fila='minhas' %}."""
    return filtros.querystring(**trocas)


@register.simple_tag
def reacoes() -> tuple[str, ...]:
    return REACOES_RAPIDAS
