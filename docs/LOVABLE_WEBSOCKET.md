# Como integrar o WebSocket de notificações no Lovable

Este documento explica como um front feito no Lovable deve se conectar e consumir o WebSocket de notificações do backend atual, preservando todo o comportamento existente.

Resumo das opções suportadas (mantendo o comportamento atual)
- Modo padrão (já existente): autenticação por sessão/cookie do Django — funciona se o Lovable compartilhar os cookies de sessão do domínio.
- Novo modo (adicionado): autenticação via JWT por querystring — use `?token=<ACCESS_TOKEN>` ao abrir o WebSocket. Isso permite que um frontend separado (Lovable) autentique sem depender de cookies.

Endpoint
- `wss://<API_HOST>/ws/notifications/` (usar `wss://` em produção)

Autenticação

1) Sessão/Cookie (padrão — já em uso)
   - Se o Lovable carregar em um contexto onde os cookies de sessão do Django estejam presentes e enviados pelo navegador, basta abrir o WebSocket normalmente para `wss://.../ws/notifications/`.

2) JWT via querystring (novo, recomendado para front separado)
   - Gere/recupere um `access_token` (por exemplo, via login na API REST — `rest_framework_simplejwt`).
   - Abra o WebSocket com `?token=<ACCESS_TOKEN>`:

```javascript
const token = localStorage.getItem('access_token');
const wsScheme = location.protocol === 'https:' ? 'wss' : 'ws';
const wsUrl = `${wsScheme}://api.exemplo.com/ws/notifications/?token=${encodeURIComponent(token)}`;
const socket = new WebSocket(wsUrl);
```

- No backend o `JwtAuthMiddleware` (adicionado) valida o token e preenche `scope['user']`. Se o token for válido, a conexão será autenticada como o usuário do token.
- Se o token for inválido ou ausente, o backend continuará a usar a autenticação por sessão/cookie (comportamento atual), ou recusará a conexão se nenhum método autenticar o usuário.

Formato da mensagem recebida

Os payloads são JSON com este formato (campos atuais):

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

Fluxo de uso (no cliente Lovable)

1. Obter token de autenticação (se usar JWT) ou garantir cookies de sessão.
2. Abrir conexão WebSocket em `wss://<API_HOST>/ws/notifications/` (adicionar `?token=` se usar JWT).
3. Tratar eventos `onmessage` parseando JSON e exibindo notificações.
4. Usar `notification_id` para evitar duplicações (idempotência da UI).
5. Marcar notificações como lidas via API quando apropriado.

Exemplo completo (recomendações práticas)

```javascript
class NotificationsClient {
  constructor({apiHost, token}){
    this.apiHost = apiHost;
    this.token = token;
    this.ws = null;
    this.retryDelay = 1000;
    this.seen = new Set(); // para deduplicar por notification_id
  }

  connect(){
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    let url = `${scheme}://${this.apiHost}/ws/notifications/`;
    if(this.token) url += `?token=${encodeURIComponent(this.token)}`;

    this.ws = new WebSocket(url);

    this.ws.onopen = () => { console.log('WS conectado'); this.retryDelay = 1000; };

    this.ws.onmessage = (e) => {
      try{
        const data = JSON.parse(e.data);
        if(!data.notification_id || this.seen.has(data.notification_id)) return;
        this.seen.add(data.notification_id);
        this.onNotification(data);
      } catch(err){ console.error('WS parse error', err); }
    };

    this.ws.onclose = () => {
      console.log('WS fechado, reconectando em', this.retryDelay);
      setTimeout(() => this.connect(), this.retryDelay);
      this.retryDelay = Math.min(30000, this.retryDelay * 2);
    };

    this.ws.onerror = (err) => console.error('WS error', err);
  }

  onNotification(data){
    // integrar com o Lovable: exibir badge, toast, etc.
    console.log('Notificação recebida', data);
  }
}

// Uso
const client = new NotificationsClient({ apiHost: 'api.exemplo.com', token: localStorage.getItem('access_token') });
client.connect();
```

Boas práticas e pontos operacionais

- Sempre use `wss://` em produção (TLS).
- Preferir enviar o `access_token` temporário (short-lived) — tokens long-lived aumentam risco caso vazem.
- Tome cuidado com exposição de tokens em logs quando usar querystring (não enviar tokens em URLs de páginas ou referers em navegadores externos).
- Para maior segurança, considere usar `Sec-WebSocket-Protocol` (subprotocol) para transportar o token em vez de querystring — isso exigirá ajuste no middleware para ler `sec-websocket-protocol` no scope.
- Use `notification_id` para idempotência no frontend e, quando o usuário visualizar a notificação, chame a API para marcar como lida.

API útil (backend)

- Endpoint para marcar notificação como lida (não criado aqui) provavelmente existe via `notifications` app — usar a API para atualizar estado `read`.

Suporte e próximos passos

Se quiser eu:
- adapto o middleware para aceitar token via `Sec-WebSocket-Protocol` (subprotocol) ao invés de querystring;
- gero um componente Lovable (JS) embutido pronto para copiar e colar;
- adiciono exemplos de marcação de leitura via API.
