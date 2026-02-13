# WebSocket de Notificações — estado atual (apenas implementação atual)

Este documento descreve como o WebSocket de notificações está funcionando hoje no backend Django/Channels — apenas o comportamento e os pontos de integração atuais, sem alternativas.

**Resumo rápido**
- Endpoint WebSocket exposto: `ws(s)://<HOST>/ws/notifications/`
- Autenticação atual: `AuthMiddlewareStack` (autenticação por sessão/cookie do Django)
- Organização: cada usuário tem um grupo com nome `user_<user_id>`
- Mensagens enviadas ao cliente: JSON com campos `verb`, `description`, `target_url`, `timestamp`, `notification_id` (ver abaixo)

**Onde olhar no código**
- Consumer: [notificacao/consumers.py](notificacao/consumers.py#L1-L50)
- Routing do WS: [notificacao/routing.py](notificacao/routing.py#L1-L20)
- Função que envia as notificações: [notificacao/utils.py](notificacao/utils.py#L1-L80)
- ASGI / middleware: [core/asgi.py](core/asgi.py#L1-L40)
- Configuração do channel layer (Redis): [core/settings.py](core/settings.py#L1-L200)

Fluxo de conexão (atual)

1. O cliente conecta para `ws(s)://<HOST>/ws/notifications/`.
2. `AuthMiddlewareStack` (em `core/asgi.py`) popula `scope['user']` a partir da sessão/cookie do Django.
3. No `NotificationConsumer.connect()` (em `notificacao/consumers.py`) o backend verifica `self.scope['user'].is_authenticated`: se verdadeiro, a conexão é adicionada ao grupo `user_<id>` e o socket é aceito; se falso, a conexão é fechada.

Como as notificações são enviadas (atual)

- O backend usa o channel layer (Channels + Redis) para enviar mensagens ao grupo do usuário. Em `notificacao/utils.py` existe um chamado a:

```python
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

channel_layer = get_channel_layer()
async_to_sync(channel_layer.group_send)(
    f"user_{usuario.id}",
    {
        "type": "send_notification",
        "verb": verb,
        "description": description,
        "target_url": target_url or instance.get_absolute_url(),
        "timestamp": timestamp,
        "notification_id": notification_id,
        "type_notification": type_notification,  # opcional
    }
)
```

- `type: "send_notification"` faz com que o `NotificationConsumer` invoque seu método `send_notification`, que envia ao cliente um JSON com os campos abaixo.

Formato da mensagem enviada ao cliente

O payload enviado pelo consumer ao cliente é JSON com esta estrutura (campos atuais):

```json
{
  "verb": "string",
  "description": "string",
  "target_url": "string",
  "timestamp": "DD/MM HH:mm",
  "notification_id": 123,
  "type_notification": "optional string"
}
```

Configuração do backend relevante

- `core/asgi.py` usa `ProtocolTypeRouter` com `AuthMiddlewareStack` para WebSocket routing: o `AuthMiddlewareStack` depende da sessão do Django para autenticação.
- `core/settings.py` define `ASGI_APPLICATION = 'core.asgi.application'` e `CHANNEL_LAYERS` apontando para `channels_redis.core.RedisChannelLayer` com `hosts: [("redis", 6379)]` — portanto o Redis deve estar disponível para o channel layer.

Cliente — como se comporta com a implementação atual

- Como o backend depende de sessão/cookie para autenticação, o cliente funciona sem enviar cabeçalhos adicionais desde que:
  - o cliente esteja no mesmo domínio (ou compartilhe cookies de sessão) e o navegador envie o cookie de sessão automaticamente,
  - ou o WebView/ambiente do Lovable exponha os cookies do Django ao criar a conexão WebSocket.

Exemplo mínimo de conexão (mesmo domínio / cookies disponíveis)

```javascript
const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
const wsUrl = `${wsScheme}://${window.location.host}/ws/notifications/`;
const socket = new WebSocket(wsUrl);


socket.onmessage = (e) => {
  const data = JSON.parse(e.data);
  // usar data.verb, data.description, data.target_url, data.timestamp, data.notification_id
  mostrarNotificacao(data);
};
socket.onclose = () => console.log('WS fechado');

function mostrarNotificacao(data) {
  console.log('Notificação:', data);
}
```

Observações finais (estado atual)

- Autenticação: atualmente baseada em sessão/cookie via `AuthMiddlewareStack`. O backend NÃO tem, hoje, um middleware ASGI no repositório que leia um token JWT da querystring e autentique automaticamente para WebSocket — portanto a forma suportada por padrão é sessão/cookie.
- Channel layer: `channels_redis` é usado (ver `core/settings.py`), portanto o Redis precisa estar configurado.
- Mensagens: o payload atual é JSON simples; clientes devem parsear o JSON e usar `notification_id` para evitar duplicação na UI.

Se quiser, eu faço uma pequena edição no backend para adicionar um middleware JWT ASGI (para aceitar token em querystring) ou crio um componente cliente específico para o Lovable; diga qual prefere.

**Fluxo completo de uso (passo-a-passo técnico)**

1. Acontece um evento no backend (view, signal ou ação da API) que precisa notificar um ou mais usuários. Exemplos:
  - criação de `AnaliseCreditoCliente` (nova análise);
  - mudança de status da análise (aprovar/rejeitar);
  - vendedor confirma instalação / analista informa IMEI / confirma iCloud;
  - nova `EntradaEstoque` criada;
  - pagamento informado em `Parcela`.

2. O código cria a notificação persistida usando `django-notifications`:

  ```python
  notify.send(instance, recipient=user, verb=verb, description=description, target=target)
  ```

  - Exemplos de locais que chamam `notify.send(...)`: `vendas/views.py`, `vendas/signals.py`, `notificacao/signals.py`, `api/views.py`.

3. Após criar a notificação, o backend recupera a última notificação não-lida do usuário:

  ```python
  ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
  ```

4. Se houver `ultima_notificacao`, o backend chama `enviar_ws_para_usuario(...)` passando o `usuario`, `instance`, `notification_id`, `verb`, `description`, `target_url` e `type_notification` (opcional).

  - Função: `notificacao/utils.py::enviar_ws_para_usuario`
  - O conteúdo enviado para o channel layer inclui `"type": "send_notification"` e o restante do payload.

5. `enviar_ws_para_usuario` faz `async_to_sync(channel_layer.group_send)(f"user_{usuario.id}", payload)` — isto publica a mensagem no grupo do usuário no channel layer (Redis).

6. No lado do ASGI, `core/asgi.py` roteia WebSocket via `AuthMiddlewareStack` e `URLRouter(websocket_urlpatterns)`. O route usado é `^ws/notifications/$` (ver `notificacao/routing.py`).

7. `NotificationConsumer` (em `notificacao/consumers.py`) aceita conexões apenas se `self.scope['user'].is_authenticated`; então adiciona a conexão ao grupo `user_<id>` com `group_add`.

8. Quando o channel layer entrega a mensagem ao grupo `user_<id>`, Channels invoca o método `send_notification` do consumer (por causa do `type: "send_notification"`). Esse método envia ao cliente o JSON com os campos:

  - `verb`, `description`, `target_url`, `timestamp`, `notification_id`, `type_notification` (opcional)

9. Cliente (UI/Lovable) recebe a mensagem, faz parse do JSON e renderiza a notificação.

10. Recomendações operacionais no frontend:
   - usar `notification_id` para deduplicação/idempotência;
   - implementar reconexão com backoff; marcar notificações como lidas via API quando apropriado;
   - garantir que cookies de sessão estão disponíveis se usar `AuthMiddlewareStack` (modo atual).

**Principais arquivos / locais para inspeção**
- `notificacao/utils.py` — `enviar_ws_para_usuario` (envia ao channel layer) [notificacao/utils.py](notificacao/utils.py#L1-L80)
- `notificacao/consumers.py` — `NotificationConsumer` (`connect`, `send_notification`) [notificacao/consumers.py](notificacao/consumers.py#L1-L50)
- `notificacao/routing.py` — rota `^ws/notifications/` [notificacao/routing.py](notificacao/routing.py#L1-L20)
- `core/asgi.py` — `AuthMiddlewareStack` + `URLRouter` [core/asgi.py](core/asgi.py#L1-L40)
- `core/settings.py` — `ASGI_APPLICATION` e `CHANNEL_LAYERS` (Redis) [core/settings.py](core/settings.py#L1-L200)
- Pontos que disparam notificações (exemplos):
  - `notificacao/signals.py` — criação de análises, mudanças de status, `EntradaEstoque` (usa `notify.send` + `enviar_ws_para_usuario`) [notificacao/signals.py](notificacao/signals.py#L1-L220)
  - `vendas/signals.py` — notificação de pagamento informado (`Parcela`) [vendas/signals.py](vendas/signals.py#L1-L160)
  - `vendas/views.py` — confirmar instalação, informar IMEI, confirmar iCloud etc. (chama `notify.send` e `enviar_ws_para_usuario`) [vendas/views.py](vendas/views.py#L960-L1040) [vendas/views.py](vendas/views.py#L3320-L3560)
  - `api/views.py` — endpoints equivalentes que disparam notificações [api/views.py](api/views.py#L820-L1160)

**Resumo das implicações**
- A autenticação atual exige sessão/cookie; clientes externos precisam ter essa sessão disponível.
- Redis é obrigatório para o channel layer funcionar conforme configurado.
- O backend envia a notificação persistida (django-notifications) e, em seguida, envia via channel layer a versão JSON para os sockets conectados.

---
Atualizei o documento com o fluxo completo; marquei a tarefa de edição como concluída.

