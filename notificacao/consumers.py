from channels.generic.websocket import AsyncWebsocketConsumer
import json

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if self.scope["user"].is_authenticated:
            self.group_name = f"user_{self.scope['user'].id}"
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, code):
        if self.scope["user"].is_authenticated:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def crm_evento(self, event):
        """Evento do CRM de WhatsApp: só tipo e id da conversa (a tela recarrega pela API)."""
        await self.send(text_data=json.dumps({
            "event": "crm.evento",
            "tipo": event.get("tipo"),
            "conversa_id": event.get("conversa_id"),
            "para_mim": bool(event.get("para_mim")),
        }))

    async def send_notification(self, event):
        await self.send(text_data=json.dumps({
            "verb": event["verb"],
            "description": event["description"],
            "target_url": event["target_url"],
            "timestamp": event["timestamp"],
            "notification_id": event["notification_id"],
            "type_notification": event.get("type_notification"),
            "event": event.get("event"),
        }))

