"""Notificação (sino + WebSocket) para todos os usuários de um conjunto de grupos."""
from notifications.signals import notify

from accounts.models import User
from notificacao.utils import enviar_ws_para_usuario

GRUPOS_ANALISE = ('ADMINISTRADOR', 'ANALISTA')
GRUPOS_ANALISE_E_VENDAS = ('VENDEDOR', 'ADMINISTRADOR', 'ANALISTA')
TIPO_NOTIFICACAO_ANALISE = 'analise_credito_cliente'


def notificar_grupos(
    *, grupos, autor, instance, target, verb: str, description: str,
    target_url: str | None = None, type_notification: str = TIPO_NOTIFICACAO_ANALISE,
) -> int:
    """Cria a notificação para cada usuário dos grupos (menos o autor) e envia pelo WS.

    Devolve quantos usuários foram notificados. Um usuário em mais de um grupo
    recebe uma única notificação.
    """
    destinatarios = (
        User.objects.filter(groups__name__in=grupos)
        .exclude(id=getattr(autor, 'id', None))
        .distinct()
    )
    url = target_url or target.get_absolute_url()
    total = 0
    for usuario in destinatarios:
        notify.send(instance, recipient=usuario, verb=verb, description=description, target=target)
        ultima = usuario.notifications.unread().order_by('-timestamp').first()
        if ultima:
            enviar_ws_para_usuario(
                usuario=usuario,
                instance=instance,
                notification_id=ultima.id,
                verb=verb,
                description=description,
                target_url=url,
                type_notification=type_notification,
            )
        total += 1
    return total
