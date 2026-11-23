# Deploy da Fase 0 de segurança

Checklist para publicar o endurecimento do backend (`openspec/changes/backoffice-react`,
tasks 0.x). Leia tudo **antes** do push no `main`: o deploy automático (`.github/workflows/deploy.yml`)
reconstrói a imagem porque `Dockerfile` e `docker-compose.yml` mudaram.

## 1. Variáveis de ambiente (`/root/credfacil/.env`)

| Variável | Obrigatória | Valor de produção / observação |
|---|---|---|
| `SECRET_KEY` | **sim** | Sem ela o Django não sobe (fora da suíte de testes). Use a mesma de hoje para não derrubar sessões e JWT. |
| `DEBUG` | não | Padrão `False`. Nunca `True` em produção. |
| `ALLOWED_HOSTS` | **sim** | Domínio da API/telas Django **e** o domínio da SPA nova do backoffice (proxy reverso), ex.: `credfacil.mobconnects.com,painel.exemplo.com.br`. |
| `CSRF_TRUSTED_ORIGINS` | **sim** | Com esquema: `https://credfacil.mobconnects.com,https://<domínio da SPA nova>`. |
| `CORS_ALLOWED_ORIGINS` | **sim** | Origem da SPA do vendedor (`front-connect-magic`), ex.: `https://vendas.exemplo.com`. Sem ela a SPA do vendedor para (CORS) e o WebSocket dela é recusado (validação de origem). |
| `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` | não | Padrão `True` com `DEBUG=False`. Só desligue em ambiente sem HTTPS. |
| `SECURE_HSTS_SECONDS` | não | Padrão `0`. Depois de confirmar HTTPS em todos os domínios: `31536000`. `SECURE_HSTS_INCLUDE_SUBDOMAINS=True` só se todos os subdomínios tiverem HTTPS. |
| `AXES_PROXY_COUNT` | não | Padrão `1` (nginx do host na frente). É usado pelo django-axes, pelos limites do DRF (`NUM_PROXIES`) e pelo limite das views Django. Precisa bater com o número real de proxies. |
| `AXES_ENABLED`, `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_MINUTOS` | não | Padrões: ligado, 5 falhas, 15 min. |
| `THROTTLE_ANON`, `THROTTLE_USER`, `THROTTLE_LOGIN`, `THROTTLE_PUBLICO` | não | Padrões `60/min`, `600/min`, `10/min`, `20/min`. `login`: `/api/token/`, `/api/token/logout/`, recuperação de senha (POST). `publico`: `/api/buscar-lojas/`, `/buscar-lojas/`, `/api/contrato/<uuid>/`, `/consultar-pagamentos/` (POST). O contador fica no cache local de cada worker (o limite efetivo é taxa × `WEB_CONCURRENCY`). |
| `REDIS_PASSWORD` | **sim** | O `docker-compose.yml` recusa subir sem ela (`--requirepass`). As settings montam `redis://:senha@redis:6379` para o channel layer e o cache do select2. Gere com `openssl rand -hex 32`. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | sim para reset de senha | Sem `EMAIL_HOST` o e-mail vai para o console (link de reset nos logs). |
| `MIDIA_ASSINATURA_HORAS` | não | Validade das URLs de mídia assinadas. Padrão `6`. |
| `MIDIA_X_ACCEL_PREFIXO` | recomendado | Ex.: `/_midia/`. Com ele o Django só confere a assinatura e o nginx entrega o arquivo (ver seção 2). Vazio = o Django entrega o arquivo. |
| `SENTRY_DSN`, `SENTRY_SEND_DEFAULT_PII` | não | Vazio desliga o Sentry. |
| `BACKOFFICE_SPA_URL` | quando a SPA nova entrar | URL pública da SPA nova, ex.: `https://painel.exemplo.com.br`. |
| `BACKOFFICE_SPA_MODULOS` | não | Módulos cujas telas Django redirecionam para a SPA nova (ex.: `credito,vendas`). Vazio = nada muda. |
| `BACKOFFICE_SESSAO_INATIVIDADE_MIN`, `BACKOFFICE_SESSAO_MAXIMA_HORAS` | não | Padrões `30` e `12`. |

## 2. nginx do servidor

1. **Mídia:** remova qualquer `location /mediafiles/ { alias ...; }` que sirva o disco direto: ela
   pula a assinatura e deixa RG, Serasa e fotos públicos de novo. `/mediafiles/` passa a ir para o
   Django como o resto. Para o nginx entregar os arquivos (recomendado), defina
   `MIDIA_X_ACCEL_PREFIXO=/_midia/` e crie uma location **internal**:

   ```nginx
   location /_midia/ {
       internal;                                   # só via X-Accel-Redirect do Django
       alias /root/credfacil/mediafiles/;
       add_header X-Content-Type-Options nosniff always;
   }
   ```

2. **IP real:** o proxy para `127.0.0.1:8010` precisa enviar
   `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` e
   `proxy_set_header X-Forwarded-Proto $scheme;`. Sem o primeiro, todos os clientes viram o mesmo
   IP nos limites de tentativas e no axes.
3. **WebSocket:** `/ws/` continua com `Upgrade`/`Connection` como hoje. O Django passa a recusar
   origem fora de `ALLOWED_HOSTS` + `CORS_ALLOWED_ORIGINS`.
4. **Porta 8010:** continua publicada no host porque o nginx do host depende dela. Bloqueie-a para
   fora no firewall (`ufw deny 8010` ou regra equivalente; o Docker fura o ufw em portas publicadas,
   então prefira `127.0.0.1:8010:8010` no compose quando puder confirmar que o nginx usa `127.0.0.1`).
5. **Redis:** deixa de ser publicado no host (antes `6385`). Se algo fora do Docker usava essa porta,
   passa a falhar de propósito.

## 3. Container sem root

A imagem agora roda como o usuário `app` (UID/GID `1000`, ajustáveis com `--build-arg APP_UID/APP_GID`)
e não baixa mais o oh-my-zsh. As pastas montadas por volume precisam ser graváveis por ele
**antes** de subir a imagem nova (senão o gunicorn não abre `logs/django_debug.log` e o
container entra em loop de reinício):

```bash
cd /root/credfacil
mkdir -p mediafiles mediafiles_privado logs staticfiles
chown -R 1000:1000 mediafiles mediafiles_privado logs staticfiles
chmod 640 .env && chown root:1000 .env      # o app lê o .env (load_dotenv)
```

`mediafiles_privado/` (mídia do CRM) e `staticfiles/` (collectstatic do passo 8 do deploy) também
são gravados pelo container. O resto do código montado (`.:/app`) só precisa de leitura.

## 4. Ordem segura de deploy

1. Backup do banco e de `mediafiles/` (o passo de migração preenche `Pagamento.token_publico`).
2. No servidor: complete o `.env` (seção 1), em especial `REDIS_PASSWORD`, `CORS_ALLOWED_ORIGINS`,
   `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SECRET_KEY`.
3. No servidor: rode o `chown` da seção 3.
4. Ajuste o nginx (seção 2), **sem** recarregar ainda a remoção do `/mediafiles/` direto se o
   deploy demorar; o restante pode entrar antes.
5. Push no `main`. O workflow reconstrói a imagem, roda `migrate` (aplica `vendas.0158`/`0159`,
   `token_blacklist` e `axes`) e `collectstatic`, e reinicia `web`, `crm-worker` e `redis`.
   Confirme que o Redis novo subiu: `docker compose ps` e `docker compose logs redis`.
6. `nginx -t && systemctl reload nginx` com a location de mídia nova.
7. Teste os fluxos da seção 5. Se algo quebrar: reverta o commit e rode o deploy de novo (as
   migrações 0158/0159 só acrescentam a coluna; não precisam ser revertidas).

## 5. Como testar depois do deploy

**SPA do vendedor** (`front-connect-magic`, apontando para a produção):

- login (a lista de lojas aparece ao digitar o usuário; usuário inexistente mostra "nenhuma loja");
- lista e detalhe de solicitações; nova solicitação com fotos (JPG/PNG/PDF até 10 MB; outros tipos
  agora voltam com erro no campo);
- confirmar leitura do QR, configurar iCloud, cancelar, gerar venda;
- documentos da venda (envio e visualização: as imagens abrem com `?assinatura=` na URL);
- detalhe da loja, aba "Agendados";
- notificações em tempo real (WebSocket conecta; se não conectar, confira `CORS_ALLOWED_ORIGINS`).

**Telas Django:** login (bloqueio após 5 falhas), aprovar pelo botão "Aprovar" da edição da
solicitação (agora aprova no mesmo POST), toggles de situação do pagamento, "Marcar todas como lida",
consulta pública de pagamentos por CPF (o link de cada pagamento é `/pagamento/<uuid>/`; o link
antigo `/pagamento/<id>/` leva à consulta), painel do cliente no CRM ("Parcelas").

**Segurança, por fora:**

- `curl -I https://<api>/mediafiles/<algum caminho>` → 404;
- `redis-cli -h <ip do servidor> -p 6385 ping` → recusado;
- `curl https://<api>/api/schema/` sem login de staff → 401/403.

## 6. Mudanças de API que um cliente externo pode notar

- `POST /api/token/logout/` com `{"refresh": "..."}` põe o refresh na blacklist (a SPA do vendedor
  pode passar a chamar no logout; não é obrigatório).
- `POST /api/solicitacoes/{id}/aprovar|reprovar|status-app/` exigem `vendas.change_status_analise`.
- Ações de solicitação em cliente de outra loja respondem 404 (antes 403 ou executavam).
- `/api/repasses/` exige `financeiro.*_repasse` e só mostra as lojas do usuário.
- `UserSerializer`: `is_superuser`, `is_staff` e `user_permissions` são só leitura; `groups` só
  aceita grupos com permissões que quem edita tem; `loja` só uma loja do escopo de quem edita; senha
  passa pelos validadores (erro no campo `password`).
- `/api/buscar-lojas/` e `/buscar-lojas/`: usuário inexistente responde `200 {"lojas": []}`.
