"""Envio de notificações em tempo real (WebSocket) para um usuário.

O envio é best-effort e NUNCA roda dentro do request:

1. só é agendado depois do commit da transação (`transaction.on_commit`);
2. roda numa thread de fundo própria (não na thread do request);
3. cada `group_send` tem timeout (`NOTIFICACAO_WS_TIMEOUT`).

Motivo (incidente de 2026-11-12): um `group_send` travado dentro do request de
criação de pré-análise, ao ser cancelado pelo servidor ASGI, bloqueou o event
loop inteiro e derrubou o sistema por ~35 minutos.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils.timezone import localtime

logger = logging.getLogger(__name__)

TIMEOUT_PADRAO_SEGUNDOS = 3.0

# Uma única thread: os envios saem na ordem em que foram gerados (o front abre
# modais pelo campo `event`, ex. 'proposta_criada' antes de 'proposta_aceita').
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="notificacao-ws")


def _timeout() -> float:
    return float(getattr(settings, "NOTIFICACAO_WS_TIMEOUT", TIMEOUT_PADRAO_SEGUNDOS))


def _montar_mensagem(instance, notification_id, verb, description, target_url,
                     type_notification, event) -> dict[str, Any]:
    return {
        "type": "send_notification",
        "verb": verb,
        "description": description,
        "target_url": target_url or instance.get_absolute_url(),
        "timestamp": localtime(instance.criado_em).strftime('%d/%m %H:%M'),
        "notification_id": notification_id,
        "type_notification": type_notification,
        # Evento semantico que dispara modais no front (ex.: 'proposta_criada',
        # 'proposta_aceita', 'proposta_negada', 'proposta_cancelada'). None => sem modal.
        "event": event,
    }


async def _group_send_com_timeout(grupo: str, mensagem: dict[str, Any], timeout: float) -> None:
    await asyncio.wait_for(get_channel_layer().group_send(grupo, mensagem), timeout=timeout)


def _enviar_agora(grupo: str, mensagem: dict[str, Any]) -> None:
    timeout = _timeout()
    try:
        async_to_sync(_group_send_com_timeout)(grupo, mensagem, timeout)
    except asyncio.TimeoutError:
        logger.warning("Notificação WS para %s abortada: sem resposta do Redis em %.1fs.", grupo, timeout)
    except Exception:  # noqa: BLE001 — notificação em tempo real é best-effort
        logger.warning("Falha ao enviar notificação WS para %s (ignorada).", grupo, exc_info=True)


def _despachar(grupo: str, mensagem: dict[str, Any]) -> None:
    if getattr(settings, "NOTIFICACAO_WS_SINCRONO", False):
        _enviar_agora(grupo, mensagem)
        return
    try:
        _executor.submit(_enviar_agora, grupo, mensagem)
    except RuntimeError:  # executor encerrado (worker desligando)
        logger.warning("Notificação WS para %s descartada: servidor desligando.", grupo)


def enviar_evento_ws(usuario_id: int, mensagem: dict[str, Any]) -> None:
    """Agenda um evento genérico (ex.: CRM) para o grupo do usuário, depois do commit.

    `mensagem['type']` precisa existir como handler no NotificationConsumer.
    """
    grupo = f"user_{usuario_id}"
    transaction.on_commit(lambda: _despachar(grupo, mensagem))


def enviar_ws_para_usuario(usuario, instance, notification_id, verb, description, target_url,
                           type_notification=None, event=None) -> None:
    """Agenda o push WS para o usuário; retorna na hora, sem esperar o Redis."""
    mensagem = _montar_mensagem(instance, notification_id, verb, description, target_url,
                                type_notification, event)
    grupo = f"user_{usuario.id}"
    transaction.on_commit(lambda: _despachar(grupo, mensagem))
