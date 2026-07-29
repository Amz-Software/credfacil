from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils.timezone import localtime
from django.contrib.humanize.templatetags.humanize import naturaltime

def enviar_ws_para_usuario(usuario, instance, notification_id, verb, description, target_url, type_notification=None, event=None):
    channel_layer = get_channel_layer()
    timestamp = localtime(instance.criado_em).strftime('%d/%m %H:%M')

    async_to_sync(channel_layer.group_send)(
        f"user_{usuario.id}",
        {
            "type": "send_notification",
            "verb": verb,
            "description": description,
            "target_url": target_url or instance.get_absolute_url(),
            "timestamp": timestamp,
            "notification_id": notification_id,
            "type_notification": type_notification,
            # Evento semantico que dispara modais no front (ex.: 'proposta_criada',
            # 'proposta_aceita', 'proposta_negada', 'proposta_cancelada'). None => sem modal.
            "event": event,
        }
    )
