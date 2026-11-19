"""Avisos do CRM: eventos em tempo real pelo WebSocket existente e notificações no sino.

Tudo é best-effort e sai depois do commit (notificacao.utils). O payload do evento
não leva conteúdo da conversa (LGPD): só o tipo e o id.
"""
import logging

from crm.permissoes import usuarios_com_acesso

logger = logging.getLogger(__name__)

URL_CONVERSA = '/app/crm?conversa={id}'


def _para_mim(conversa, usuario_id: int) -> bool:
    from crm.models import Conversa

    if conversa.modo == Conversa.Modo.AGUARDANDO:
        return True
    if conversa.modo == Conversa.Modo.HUMANO:
        return conversa.assumida_por_id in (None, usuario_id)
    return False


def emitir(conversa, tipo: str) -> None:
    """Avisa todos que acessam o CRM que a conversa mudou (a tela recarrega)."""
    from notificacao.utils import enviar_evento_ws

    try:
        for usuario_id in usuarios_com_acesso().values_list('id', flat=True):
            enviar_evento_ws(usuario_id, {
                'type': 'crm_evento',
                'event': 'crm.evento',
                'tipo': tipo,
                'conversa_id': conversa.pk,
                'para_mim': _para_mim(conversa, usuario_id),
            })
    except Exception:  # noqa: BLE001 — aviso nunca quebra o fluxo
        logger.warning('Falha ao emitir evento do CRM (ignorada).', exc_info=True)


def notificar_usuario(usuario, texto: str, conversa) -> None:
    """Notificação persistente no sino (atribuição, puxada, lembrete, erro de programada)."""
    if usuario is None:
        return
    from notifications.signals import notify

    from notificacao.utils import enviar_ws_para_usuario

    try:
        resultados = notify.send(conversa, recipient=usuario, verb=texto, description='CRM de WhatsApp',
                                 target=conversa)
        notificacoes = resultados[0][1] if resultados else []
        notificacao_id = notificacoes[0].id if notificacoes else None
        enviar_ws_para_usuario(usuario, conversa, notificacao_id, texto, 'CRM de WhatsApp',
                               URL_CONVERSA.format(id=conversa.pk), type_notification='crm')
    except Exception:  # noqa: BLE001
        logger.warning('Falha ao notificar %s sobre o CRM (ignorada).', usuario, exc_info=True)
