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
| `ANTHROPIC_API_KEY` | não | Liga o assistente de IA (Claude) quando ele também está ativo na Configuração |
| `WHATSAPP_CHAMADAS_PHONE_NUMBER_ID` | não | Número das ligações (ex.: número de teste da Meta). Vazio = o mesmo das mensagens |
| `WHATSAPP_CHAMADAS_TOKEN` | não | Token para esse número de ligações. Vazio = `WHATSAPP_TOKEN` |
| `ASSISTENTE_MODELO` | não | Modelo do assistente. Padrão `claude-sonnet-5-5` |
| `ASSISTENTE_ESFORCO` | não | `low` (padrão), `medium`, `high`, `xhigh` ou `max` |
| `ASSISTENTE_TELEFONES_TESTE` | não | Números separados por vírgula: se preenchida, só eles falam com a IA (os demais seguem no menu). Para testar em produção |
| `CRM_MIDIA_ROOT` | não | Pasta privada da mídia quando não há S3. Padrão `mediafiles_privado/` no projeto (fora de `/mediafiles/`, que é público) |

O modo real só liga com **token e ID do número**. Com só um dos dois, continua simulado.

**Política de privacidade** (campo obrigatório para publicar o app na Meta):
`https://<domínio do backend>/privacidade/`, página pública. Razão social, CNPJ e e-mail do
responsável pelos dados ficam em CRM WhatsApp → Configuração.

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
  `AGUARDANDO`, com nota interna.
- **Assistente de IA** (Configuração → "Assistente de IA" + `ANTHROPIC_API_KEY`): em
  `AUTOMATICO`, o Claude conversa em linguagem natural no lugar do menu, como a persona
  configurada (`assistente_nome`); se perguntarem, diz que é assistente virtual. Só explica o que
  está em `assistente_conhecimento` e nas regras do crediário (tabela `Parcelamento`); o resto
  vai para a equipe. Ferramentas (`crm/services/assistente/ferramentas.py`):
  `identificar_cliente` (CPF + nascimento conferidos pelo código, 3 tentativas, vale 24 h),
  `consultar_parcelas` (inclui aparelho bloqueado e a loja da compra) e `gerar_link_pagamento`
  (só do cliente identificado; o link sai de `crm/services/links_pagamento.py`, ponto único de
  troca do gateway), `simular_antecipacao` (desconto de `antecipacao_percentual_dia` por dia, no
  máximo 50%; quem fecha é a equipe), `registrar_comprovante` (anexa a imagem/PDF do cliente como
  `ComprovanteParcela` e marca a parcela como "pagamento informado", o mesmo da página pública) e
  `transferir_para_atendente` (assunto + nota; grava `EncaminhamentoIA`). Assuntos que conduz:
  PIX, valor e atraso de parcela, comprovante, desbloqueio, antecipação, quitação, negociação,
  mudança de vencimento, IPX Consulta, atendente. Na primeira mensagem (se o cliente só
  cumprimentou) envia o menu de serviços: lista numerada + lista interativa do WhatsApp
  (`crm/services/assistente/menu.py`, ferramenta `mostrar_menu`). Vê as 2 imagens/PDFs mais
  recentes do cliente (últimos 30 min). Cliente identificado falando de outro número: o número
  entra em `TelefoneCliente` (origem "atendimento"), sem trocar o principal. Fora do horário
  comercial (`hora_abertura`/`hora_fechamento`/`hora_fechamento_sabado`; domingo e feriados
  nacionais fechados, `crm/services/expediente.py`) continua atendendo e, quando precisa da equipe,
  transfere avisando com `mensagem_fora_horario`. Respostas ficam com `dados.ia = true` e
  aparecem como "Assistente de IA". Sem chave, com falha da API ou resposta vazia, nada da IA
  é enviado e vale o fluxo abaixo (menu ou boas-vindas). Limite de 40 respostas da IA por
  hora por conversa.
- **Autoatendimento de pagamentos** (ligado em Configuração → Atendimento automático):
  em `AUTOMATICO`, o cliente recebe o menu *1 – Ver minhas parcelas* / *2 – Falar com um
  atendente*. Na opção 1 informa CPF e data de nascimento (mesma regra da consulta pública
  `/consultar-pagamentos/`) e recebe as parcelas em aberto, as atrasadas, a próxima e o link
  `<url_publica>/pagamento/<id>/` com PIX. Os clientes encontrados ficam vinculados à conversa.
  Após 3 tentativas erradas, arquivo/áudio, opção inválida duas vezes ou pedido de atendente,
  vai para a equipe com nota. A etapa expira em 30 min.
- **Avisos de cobrança** (Configuração → Avisos de cobrança, `crm/services/cobranca.py`, rodam no
  `crm-worker` a partir de `cobranca_hora_envio`): templates de utilidade (marcadores `{nome}`,
  `{valor}`, `{vencimento}`) 3 dias antes, no dia, 2 dias depois (pede comprovante) e, sem
  retorno, a cada `cobranca_intervalo_dias` até `cobranca_max_insistencias`; mensagem de quitação
  quando a última parcela é paga. Nunca para parcela paga/informada, nunca para número de
  referência, no máximo 1 aviso por cliente por dia, só parcelas que entram na régua depois de
  ligada. Cada aviso é uma `TentativaContato` (resposta do cliente → "respondeu"; erro 131026 da
  Meta → número marcado "sem WhatsApp" e o próximo aviso usa outro número validado). Política da
  Meta: empresa de cobrança de terceiros é proibida e texto em tom de ameaça é recusado; lembrete
  do próprio credor é utilidade, mas a Meta revisa cada template. Mantenha os textos informativos.
- **Compra confirmada** (`crm/services/compra_confirmada.py`): quando o vendedor gera a venda, sai para
  o cliente o template escolhido em Avisos de cobrança → "Compra confirmada" (`{nome}`, `{valor}` = 1ª
  parcela do crediário, `{vencimento}`), independente de `cobranca_ativa`. Uma vez por venda
  (`Mensagem.origem = COMPRA`, `dados.compra.venda_id`), na conversa do cliente; falha da Meta não
  desfaz a venda. A resposta de `gerar-venda/` traz `confirmacao_whatsapp` para a SPA avisar o vendedor.
- **Ligações pelo WhatsApp** (Calling API; `crm/services/chamadas.py`, `crm/whatsapp_chamadas.py`,
  `static/js/crm/chamadas.js`): a equipe atende e liga pelo navegador (WebRTC; o áudio vai direto
  navegador ↔ Meta, o servidor só troca o SDP). Recebida toca para todos do CRM e a primeira pessoa
  que atende fica com ela (e com a conversa, se estiver livre); feita exige a conversa assumida e
  permissão do cliente (botão "Pedir permissão", só com a janela de 24 h aberta). Cada ligação vira
  uma linha na conversa (tipo `CHAMADA`) e a feita vira `TentativaContato` (canal Ligação). Requisitos
  da Meta: número com limite de 2.000+ contatos/dia (o número de teste não exige), campo `calls`
  assinado no webhook do app e "Ativar ligações no número" na Configuração (manda o horário de
  atendimento). O webhook ignora mensagens e ligações de outros números da empresa.
- **Telefones e status de contato** (`crm/services/contatos.py`): números do cadastro, usados no
  atendimento, localizados no C4M (precisam ser validados) e de referência, com situação e
  histórico de tentativas; status por cliente (contato realizado, aguardando retorno, contato
  alternativo, referência sem sucesso, número inválido, sem WhatsApp, bloqueio confirmado — só
  quando a equipe confirma —, não localizado).
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
| `/crm/configuracao/` | Atendimento (boas-vindas, retorno automático, autoatendimento, assistente de IA, endereço público) e situação da integração com a Meta |
| `/crm/configuracao/aberturas/` | Mensagens de abertura: criar, editar (texto novo = versão nova enviada à Meta), consultar a Meta e, no modo simulado, simular aprovação/rejeição |
| `/crm/configuracao/cobranca/` | Avisos automáticos de cobrança: liga/desliga, horário, repetição e a mensagem de abertura de cada etapa (com textos sugeridos) |
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
