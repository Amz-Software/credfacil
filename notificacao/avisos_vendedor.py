"""Aviso "venda liberada" ao vendedor: notificação no sino, popup central no app e Web Push.

O front do vendedor abre, para o evento `venda_liberada`, a janela de gerar venda
(resumo, "Gerar venda" e "Ir para a venda").
"""
import logging

from notifications.signals import notify

from notificacao.utils import enviar_ws_para_usuario

logger = logging.getLogger(__name__)

EVENTO_VENDA_LIBERADA = 'venda_liberada'


def enviar_venda_liberada(analise, verb: str, description: str) -> bool:
    """Notifica quem criou a solicitação. Devolve se havia vendedor para avisar."""
    vendedor = analise.criado_por
    if vendedor is None:
        return False
    notify.send(analise, recipient=vendedor, verb=verb, description=description, target=analise.cliente)
    ultima = vendedor.notifications.unread().order_by('-timestamp').first()
    if ultima is None:
        return True
    try:
        enviar_ws_para_usuario(
            usuario=vendedor,
            instance=analise,
            notification_id=ultima.id,
            verb=verb,
            description=description,
            target_url=f'/app/solicitacoes/{analise.cliente_id}',
            type_notification='analise_credito_cliente',
            event=EVENTO_VENDA_LIBERADA,
        )
    except Exception:  # noqa: BLE001 — tempo real é best-effort; a notificação já ficou no sino
        logger.warning('Falha ao enviar o aviso de venda liberada pelo WebSocket (ignorada).', exc_info=True)
    return True
