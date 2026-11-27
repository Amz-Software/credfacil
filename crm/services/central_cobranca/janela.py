"""Janela de envio da cobrança: de `cobranca_hora_envio` até as 20h, fora de domingo e feriado.

Vale para a régua automática e para os disparos manuais (hora local, America/Belem).
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from crm.models import ConfiguracaoCRM
from crm.services import expediente

FIM_DOS_ENVIOS = time(20, 0)
MAX_DIAS_BUSCA = 14
SEGUNDOS_POR_MINUTO = 60


@dataclass(frozen=True)
class Janela:
    inicio: datetime
    fim: datetime


def dia_local(dia: date) -> tuple[datetime, datetime]:
    """[início, fim) do dia em Belém, sem depender das tabelas de fuso do MySQL (__date)."""
    inicio = timezone.make_aware(datetime.combine(dia, time.min))
    return inicio, inicio + timedelta(days=1)


def dia_de_envio(dia: date) -> bool:
    """Cobrança não sai em domingo nem feriado."""
    return dia.weekday() != expediente.DOMINGO and not expediente.feriado(dia)


def no_horario(config: ConfiguracaoCRM, local: datetime) -> bool:
    return config.cobranca_hora_envio <= local.time() < FIM_DOS_ENVIOS


def aberta(config: ConfiguracaoCRM, agora: datetime | None = None) -> bool:
    local = timezone.localtime(agora or timezone.now())
    return dia_de_envio(local.date()) and no_horario(config, local)


def _do_dia(config: ConfiguracaoCRM, dia: date) -> Janela | None:
    if not dia_de_envio(dia) or config.cobranca_hora_envio >= FIM_DOS_ENVIOS:
        return None
    return Janela(inicio=timezone.make_aware(datetime.combine(dia, config.cobranca_hora_envio)),
                  fim=timezone.make_aware(datetime.combine(dia, FIM_DOS_ENVIOS)))


def proxima(config: ConfiguracaoCRM, agora: datetime | None = None) -> Janela | None:
    """A janela em curso ou a próxima (hoje, se ainda não acabou)."""
    local = timezone.localtime(agora or timezone.now())
    for deslocamento in range(MAX_DIAS_BUSCA):
        janela = _do_dia(config, local.date() + timedelta(days=deslocamento))
        if janela is not None and janela.fim > local:
            return janela
    return None


def minutos_no_dia(config: ConfiguracaoCRM, dia: date, agora: datetime | None = None) -> int:
    """Minutos de envio que ainda restam no dia (o dia inteiro, se for futuro)."""
    janela = _do_dia(config, dia)
    if janela is None:
        return 0
    inicio = max(janela.inicio, timezone.localtime(agora or timezone.now()))
    return max(int((janela.fim - inicio).total_seconds() // SEGUNDOS_POR_MINUTO), 0)
