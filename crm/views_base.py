"""Base das views do CRM: 409 para regra de negócio, helpers de leitura."""
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.response import Response

from crm.services.conversas import ConflitoCRM
from crm.services.midias import ErroMidia


class TrataConflitoMixin:
    def handle_exception(self, exc):
        if isinstance(exc, ConflitoCRM):
            return Response({'detail': exc.detail, 'motivo': exc.motivo}, status=status.HTTP_409_CONFLICT)
        if isinstance(exc, ErroMidia):
            return Response({'detail': str(exc)}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def ler_datahora(valor):
    if not valor:
        return None
    data = parse_datetime(str(valor))
    if data is None:
        raise ConflitoCRM('Data e hora inválidas.')
    if data.tzinfo is None:
        from django.utils import timezone
        data = timezone.make_aware(data)
    return data


def ler_inteiro(valor, campo: str) -> int | None:
    if valor in (None, ''):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        raise ConflitoCRM(f'Valor inválido para {campo}.')
