"""Horário comercial da equipe humana.

Segunda a sexta e sábado com horários próprios (ConfiguracaoCRM); domingo e feriados
nacionais (fixos + Sexta-feira Santa) são fora do horário. Hora local (America/Belem).
"""
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from crm.models import ConfiguracaoCRM

DIAS_SEMANA = ('segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira', 'sexta-feira', 'sábado', 'domingo')
SABADO, DOMINGO = 5, 6
FERIADOS_FIXOS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)}
DIAS_ATE_SEXTA_SANTA = 2
MAX_DIAS_BUSCA = 14


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 — nome do algoritmo
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriado(dia: date) -> bool:
    return (dia.month, dia.day) in FERIADOS_FIXOS or dia == _pascoa(dia.year) - timedelta(days=DIAS_ATE_SEXTA_SANTA)


def _janela(config: ConfiguracaoCRM, dia: date) -> tuple[time, time] | None:
    if dia.weekday() == DOMINGO or feriado(dia):
        return None
    fim = config.hora_fechamento_sabado if dia.weekday() == SABADO else config.hora_fechamento
    if fim is None or fim <= config.hora_abertura:
        return None
    return config.hora_abertura, fim


def aberto(agora: datetime | None = None, config: ConfiguracaoCRM | None = None) -> bool:
    local = timezone.localtime(agora or timezone.now())
    janela = _janela(config or ConfiguracaoCRM.obter(), local.date())
    return bool(janela and janela[0] <= local.time() < janela[1])


def proxima_abertura(agora: datetime | None = None, config: ConfiguracaoCRM | None = None) -> datetime | None:
    config = config or ConfiguracaoCRM.obter()
    local = timezone.localtime(agora or timezone.now())
    for deslocamento in range(MAX_DIAS_BUSCA):
        dia = local.date() + timedelta(days=deslocamento)
        janela = _janela(config, dia)
        if janela is None:
            continue
        inicio = timezone.make_aware(datetime.combine(dia, janela[0]), local.tzinfo)
        if inicio > local:
            return inicio
    return None


def descrever(agora: datetime | None = None, config: ConfiguracaoCRM | None = None) -> str:
    """Frase para o prompt do assistente."""
    config = config or ConfiguracaoCRM.obter()
    local = timezone.localtime(agora or timezone.now())
    if aberto(local, config):
        fim = _janela(config, local.date())[1]
        return f'A equipe humana está atendendo agora (até as {fim:%H:%M}).'
    proxima = proxima_abertura(local, config)
    quando = (f'{DIAS_SEMANA[proxima.weekday()]}, {proxima:%d/%m} às {proxima:%H:%M}' if proxima
              else 'no próximo dia útil')
    return f'FORA do horário comercial da equipe humana. Próximo atendimento: {quando}.'
