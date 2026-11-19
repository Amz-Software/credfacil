# CRM de WhatsApp (API oficial da Meta)

Caixa de entrada da equipe para atender clientes pelo WhatsApp oficial (Cloud API),
adaptada de `arquitetura-bot-crm-whatsapp.md`. Tudo fica no **backoffice Django**
(app `crm`, telas em `/crm/`). A SPA React é só dos vendedores e **não** tem CRM: o
vendedor não acessa o WhatsApp da empresa. Em `/api/` só existe o webhook da Meta.

## 1. Ligar a integração

Sem as variáveis abaixo o sistema roda com o **WhatsApp simulado**: tudo funciona,
nada sai para a Meta, e a tela de configuração oferece um simulador de mensagens
recebidas.

| Variável | Obrigatória | O que é |
|---|---|---|
| `WHATSAPP_TOKEN` | sim | Token permanente do usuário do sistema (permissões `whatsapp_business_messaging` e `whatsapp_business_management`) |
| `WHATSAPP_PHONE_NUMBER_ID` | sim | ID do número de telefone (app → WhatsApp → Configuração da API) |
| `WHATSAPP_WABA_ID` | sim | ID da conta do WhatsApp Business (necessário para criar as mensagens de abertura) |
| `WHATSAPP_APP_SECRET` | sim | Chave secreta do app (Configurações do app → Básico). Sem ela o webhook recusa tudo |
| `WHATSAPP_VERIFY_TOKEN` | sim | Texto livre combinado entre o sistema e o painel da Meta no cadastro do webhook |
| `WHATSAPP_API_VERSION` | não | Padrão `v23.0` |
| `OPENAI_API_KEY` | não | Liga a transcrição de áudios recebidos (`whisper-1`) |
| `CRM_MIDIA_ROOT` | não | Pasta privada da mídia quando não há S3. Padrão `mediafiles_privado/` no projeto (fora de `/mediafiles/`, que é público) |

O modo real só liga com **token e ID do número**. Com só um dos dois, continua simulado.

**Webhook no painel da Meta** (app → WhatsApp → Configuração):
- URL de callback: `https://<domínio do backend>/api/whatsapp/webhook/`
- Token de verificação: o valor de `WHATSAPP_VERIFY_TOKEN`
- Campos assinados: `messages`

**Rotinas** (serviço `crm-worker` do `docker-compose.yml`, comando
`python manage.py crm_rotinas --loop`): envia programadas, avisa lembretes vencidos,
baixa mídias pendentes, marca envios travados, reprocessa entradas, devolve conversas
resolvidas ao atendimento automático e sincroniza o status das aberturas na Meta.

A tela **CRM WhatsApp → Configuração** (aba Geral) mostra o que está faltando, sem expor valores.

## 2. Permissões

| Permissão | Nome no admin | Libera |
|---|---|---|
| `crm.acessar_crm` | Pode acessar o CRM de WhatsApp | Ver e atender todas as conversas |
| `crm.gerenciar_crm` | Pode gerenciar o CRM de WhatsApp | Etiquetas, respostas rápidas, aberturas, configuração, atribuir qualquer conversa |

`gerenciar` só vale junto com `acessar`. Superusuário tem todas (regra do Django).
`is_staff` e grupos sem a permissão não veem o CRM. O item **Atendimento → CRM WhatsApp**
do menu lateral só aparece com `acessar_crm` (e "Configuração" só com `gerenciar_crm`).
Para liberar a equipe de atendimento, dê `acessar_crm` ao grupo dela em
Configurações → Usuários e Acessos → Grupos.

## 3. Regras de negócio (resumo)

- **Uma conversa por número** (`telefone` = `wa_id` da Meta). Histórico nunca se apaga.
- **`modo`** (quem responde): `AUTOMATICO` (atendimento automático), `AGUARDANDO` (fila sem dono),
  `HUMANO` (com dono). **`situacao`** (o que falta): `ABERTA` (cliente espera),
  `PENDENTE` (equipe respondeu, cliente deve), `RESOLVIDA`.
- **Atendimento automático:** mensagem nova em `AUTOMATICO` → envia a boas-vindas
  (se ligada, no máximo uma vez a cada 24 h por conversa) e passa a conversa para
  `AGUARDANDO`, com nota interna. A estrutura comporta um robô de IA no futuro.
- **Autoatendimento de pagamentos** (ligado em Configuração → Atendimento automático):
  em `AUTOMATICO`, o cliente recebe o menu *1 – Ver minhas parcelas* / *2 – Falar com um
  atendente*. Na opção 1 informa CPF e data de nascimento (mesma regra da consulta pública
  `/consultar-pagamentos/`) e recebe as parcelas em aberto, as atrasadas, a próxima e o link
  `<url_publica>/pagamento/<id>/` com PIX. Os clientes encontrados ficam vinculados à conversa.
  Após 3 tentativas erradas, arquivo/áudio, opção inválida duas vezes ou pedido de atendente,
  vai para a equipe com nota. A etapa expira em 30 min. Só responde a quem pediu (nada de
  cobrança ativa, proibida pela política do WhatsApp).
- **Janela de 24 h:** texto livre e mídia só até 24 h depois da última mensagem do
  cliente. Fora dela, só **mensagem de abertura** (template aprovado pela Meta).
- **Trava de resposta** (texto, mídia, reação, reenvio, programada): conversa em
  `HUMANO`, o dono é quem envia, janela aberta. Senão `409` com `detail` legível.
- **Retorno automático:** conversa `RESOLVIDA` e parada há `retorno_automatico_horas`
  volta ao atendimento automático (0 = nunca).
- **Antispam de abertura:** `409` se já saiu uma abertura nas últimas 24 h e o cliente
  não respondeu. Abertura com erro é reenviada como template (`mensagens/{id}/reenviar/`).
- **Painel do cliente:** só mostra e deixa vincular clientes que o usuário vê no resto do
  sistema (`vendas.view_cliente` e lojas dele, ou todas com `view_all_analise_credito`);
  vendas só com `vendas.view_venda`; CPF mascarado.
- **Mídia:** fica no S3 privado ou em `CRM_MIDIA_ROOT`; acesso só por URL assinada de 1 h,
  com registro em `LogAcessoMidia`.

## 4. Telas e rotas (backoffice)

Código em `crm/web/` (views finas sobre `crm/services/`), templates em
`crm/templates/crm/`, JS em `static/js/crm/caixa.js` e estilo em `static/css/crm.css`.
Os dicionários que os templates recebem são montados em `crm/apresentacao.py`.

### 4.1 Caixa de entrada (`crm.acessar_crm`)

| Rota | O quê |
|---|---|
| `GET /crm/` | Filas (Minhas, Sem dono, Automático, Todas), busca e filtros (situação, etiqueta, só não lidas, maior espera) |
| `GET /crm/conversas/<id>/` | Mesma página com a conversa aberta e o painel do cliente; zera as não lidas e manda o recibo de leitura |
| `GET /crm/lista/` e `GET /crm/conversas/<id>/parte/<cabecalho\|mensagens\|compositor\|painel>/` | Trechos de HTML que o JS recarrega |
| `GET /crm/conversas/<id>/mensagens/?antes=<id>` | Mensagens anteriores (50 por vez) |
| `GET /crm/conversas/<id>/buscar-cliente/?q=` | Busca por CPF ou nome, no escopo de lojas do usuário |
| `GET /crm/mensagens/<id>/arquivo/[?versao=miniatura]` | Mídia do storage privado. Abrir o original grava `LogAcessoMidia`; miniatura não |

Ações (todas `POST`, com CSRF): `assumir`, `puxar`, `atribuir`, `devolver`, `situacao`,
`etiquetas`, `apelido`, `vincular-cliente`, `desvincular-cliente`, `abrir` (abertura),
`enviar` (texto, ou arquivo com o texto como legenda), `digitando`, `resumo-pagamentos`,
`respostas-rapidas/<id>/previa`, `notas`, `notas/<id>/apagar`, `lembrete`,
`lembrete/concluir` e `programadas` (todas sob `/crm/conversas/<id>/`), além de
`/crm/iniciar/`, `/crm/mensagens/<id>/reenviar|reagir/` e `/crm/programadas/<id>/cancelar/`.

Resposta das ações:
- com o cabeçalho `X-Requested-With: XMLHttpRequest` (o JS da tela): JSON
  `{ok, mensagem, erro, motivo, texto, avisos, redirecionar}`; regra de negócio violada → **409**;
- sem JS: mensagem no topo e volta para `proxima` (só se for do próprio sistema) ou para a conversa.

### 4.2 Configuração (`crm.gerenciar_crm`)

| Rota | O quê |
|---|---|
| `/crm/configuracao/` | Atendimento (boas-vindas, retorno automático, autoatendimento, endereço público) e situação da integração com a Meta |
| `/crm/configuracao/aberturas/` | Mensagens de abertura: criar, editar (texto novo = versão nova enviada à Meta), consultar a Meta e, no modo simulado, simular aprovação/rejeição |
| `/crm/configuracao/respostas/` e `/crm/configuracao/etiquetas/` | Cadastros. Não se exclui: desmarque "Ativo" |
| `/crm/configuracao/simulador/` | Só sem credenciais: recebe mensagem como se fosse o cliente e mostra a conversa ao lado |

### 4.3 Tempo real

Pelo WebSocket de notificações já existente (`/ws/notifications/`), quem tem
`acessar_crm` recebe:

```json
{"event": "crm.evento", "tipo": "mensagem_nova" | "conversa_atualizada" | "mensagem_status" | "transferencia" | "atribuida", "conversa_id": 123, "para_mim": false}
```

O `static/js/notificacoes.js` repassa esse evento à página como `crm:evento` (sem som
nem sino) e a caixa de entrada recarrega a lista e, se for a conversa aberta, os trechos
dela. De reserva, a tela recarrega a cada 20 s com a aba visível. Quando o atendente
está lendo mensagens antigas, as novas não o arrastam para baixo: aparece o botão
"Novas mensagens".
