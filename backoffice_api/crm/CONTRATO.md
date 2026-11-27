# Contrato da API do CRM de WhatsApp — `/api/bo/v1/crm/`

API JSON da caixa de entrada e da configuração do CRM para a SPA do backoffice. Toda a regra
continua em `crm/services/*` (a tela Django e a SPA produzem o mesmo resultado).

## Convenções

- **Sessão do backoffice + CSRF** (cookie `sessionid` e cabeçalho `X-CSRFToken` em POST/PATCH).
- **Permissões:** `crm.acessar_crm` em tudo; `crm.gerenciar_crm` (junto com `acessar`) na
  configuração. Sem permissão → `403 proibido` ("Você não tem acesso ao CRM de WhatsApp." /
  "Só quem gerencia o CRM pode fazer isso."). Sem sessão → `401 nao_autenticado`.
- **Sem escopo de loja nas conversas:** quem tem `acessar_crm` vê todas (como hoje). `X-Loja` é
  ignorado. O **painel do cliente** e a busca de clientes aplicam o escopo de lojas do resto do
  sistema (`vendas.view_cliente` + lojas do usuário, ou todas com `view_all_analise_credito` /
  `can_view_all_stores`); vendas só com `vendas.view_venda`, pagamentos só com `vendas.view_pagamento`.
  CPF sempre mascarado (`***.456.789-**`).
- **Erros** (`{"erro": {"codigo", "mensagem", "campos"}}`):
  - `400 validacao` — formato inválido, com `campos` (ex.: `{"texto": ["Escreva a mensagem antes de enviar."]}`).
    Arquivo inválido (HEIC, vazio, > 25 MB) → `campos.arquivo`.
  - `409 conflito` — regra do CRM violada (trava de resposta, janela de 24 h, posse, antispam de
    abertura, programada já enviada...). Quando o serviço informa, vem também **`erro.motivo`**:
    `NAO_ASSUMIDA`, `OUTRO_DONO` ou `JANELA_FECHADA`.
    ```json
    {"erro": {"codigo": "conflito", "mensagem": "Assuma a conversa antes de responder.", "campos": {}, "motivo": "NAO_ASSUMIDA"}}
    ```
  - `404 nao_encontrado` — id inexistente. `405 metodo_nao_permitido` — método errado (GET numa ação).
- Datas ISO 8601 no fuso do sistema (`2026-11-23T10:15:00-03:00`); entrada sem fuso = horário do sistema.
  Valores monetários como texto decimal (`"199.90"`).
- Listas paginadas: `{count, page, page_size, total_pages, results}` (`?page=`, `?page_size=` até 100).
  Catálogos curtos para selects (`etiquetas/`, `respostas-rapidas/`, `aberturas/`, `atendentes/`) são arrays simples.
- Componentes do OpenAPI com prefixo `Crm` (`CrmMensagem`, `CrmConversaItem`...), tag `bo-crm`.

## Objetos

**ConversaItem** (lista)
```json
{"id": 12, "telefone": "5591999990000", "telefone_formatado": "+55 (91) 99999-0000",
 "contato_nome": "Maria Souza", "apelido": "", "nome_exibicao": "Maria Souza",
 "modo": "AGUARDANDO", "modo_display": "Aguardando a equipe",
 "situacao": "ABERTA", "situacao_display": "Aberta",
 "assumida_por": null, "nao_lidas": 2,
 "ultima_mensagem": {"em": "2026-11-23T10:15:00-03:00", "previa": "📷 Foto", "tipo": "IMAGEM", "direcao": "ENTRADA"},
 "janela": {"aberta": true, "expira_em": "2026-11-24T10:15:00-03:00"},
 "etiquetas": [{"id": 1, "nome": "Quente", "cor": "VERMELHO"}],
 "lembrete": {"em": "...", "texto": "Ligar", "para": {"id": 3, "nome": "Ana"}, "vencido": false},
 "tem_programada": false,
 "motivo_transferencia": {"texto": "Nova mensagem pelo WhatsApp...", "silenciosa": false, "criado_em": "..."},
 "total_clientes": 1}
```
`modo`: `AUTOMATICO` | `AGUARDANDO` (fila sem dono) | `HUMANO` (com dono). `situacao`: `ABERTA` | `PENDENTE` | `RESOLVIDA`.

**ConversaEstado** = ConversaItem + trava de resposta + ações que a tela oferece (conforto; o servidor confere de novo):
```json
{"...": "campos do item",
 "pode_responder": false,
 "bloqueio": {"motivo": "NAO_ASSUMIDA", "mensagem": "Assuma a conversa antes de responder."},
 "acoes": {"assumir": true, "puxar": false, "atribuir": false, "devolver": true, "resolver": true,
           "resolver_e_devolver": true, "reabrir": false, "marcar_pendente": true, "enviar_abertura": false}}
```

**ConversaDetalhe** = ConversaEstado + `painel` + `notas` (100 mais recentes, em ordem) + `programadas` (agendadas):
```json
{"painel": {
   "clientes": [{"id": 7, "nome": "Maria Souza", "cpf": "***.456.789-**", "telefone": "(91) 99999-0000",
                 "solicitacoes": [{"cliente_id": 7, "status": "A", "status_display": "Aprovado", "produto": "iPhone 13", "data": "..."}],
                 "vendas": [{"id": 30, "data": "...", "valor_total": "2400.00", "cancelada": false}],
                 "pagamentos": [{"pagamento_id": 41, "venda_id": 30, "produto": "iPhone 13", "parcelas_abertas": 8,
                                 "total_aberto": "1600.00", "parcelas_atrasadas": 1, "total_atrasado": "200.00",
                                 "em_confirmacao": 0, "proxima": {"numero": 3, "valor": "200.00", "vencimento": "2026-12-10"},
                                 "link_publico": "https://.../pagamento/..."}]}],
   "sugeridos": [{"id": 9, "nome": "Maria S.", "telefone": "91999990000"}]},
 "notas": [{"id": 5, "texto": "...", "autor": {"id": 3, "nome": "Ana"}, "automatica": false, "tipo": "GERAL",
            "silenciosa": false, "criado_em": "...", "pode_apagar": true}],
 "programadas": [{"id": 2, "texto": "...", "enviar_em": "...", "status": "AGENDADA", "criado_por": {"id": 3, "nome": "Ana"}, "erro": ""}]}
```
`link_publico` vem vazio sem "Endereço público" na configuração.

**Mensagem**
```json
{"id": 501, "direcao": "SAIDA", "autor": "HUMANO", "autor_display": "Equipe", "autor_nome": "Ana Lima",
 "tipo": "IMAGEM", "tipo_display": "Imagem", "texto": "Veja", "status": "ENTREGUE", "status_display": "Entregue",
 "erro": "", "origem": "", "criado_em": "...",
 "responde_a": {"id": 498, "tipo": "TEXTO", "texto": "Tem foto?", "autor": "Cliente"},
 "reacao_cliente": "👍", "reacao_equipe": "",
 "midia": {"status": "OK", "mime": "image/png", "nome_original": "foto.png", "tamanho_bytes": 20480,
           "duracao_s": null, "largura": 40, "altura": 30, "voz": false, "tem_miniatura": true,
           "url": "/api/bo/v1/crm/mensagens/501/arquivo/", "url_miniatura": "/api/bo/v1/crm/mensagens/501/arquivo/?versao=miniatura"},
 "dados": {}, "transcricao_status": "", "pode_reenviar": false}
```
- `direcao`: `ENTRADA` (cliente) | `SAIDA`. `autor`: `CLIENTE` | `AUTOMATICO` | `HUMANO` | `SISTEMA`.
- `tipo`: `TEXTO`, `AUDIO`, `IMAGEM`, `VIDEO`, `DOCUMENTO`, `FIGURINHA`, `LOCALIZACAO`, `CONTATO`, `DESCONHECIDO`.
- `status`: `RECEBIDO` (entrada) | `PENDENTE` → `ENVIADO` → `ENTREGUE` → `LIDO` | `ERRO` (com `erro` legível; `pode_reenviar`).
- `origem`: `""`, `ABERTURA`, `BOAS_VINDAS`, `PROGRAMADA`.
- `midia` é `null` em tipos sem arquivo; `url` só com `status = "OK"`. `dados` traz `localizacao`, `contatos`, `encaminhada`.
- Áudio recebido: transcrição em `texto` quando `transcricao_status = "OK"`.

## Caixa de entrada (`crm.acessar_crm`)

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| GET | `contexto/` | — | `{simulado, pode_gerenciar, ve_clientes, ve_pagamentos, filas[], ordens[], situacoes[], cores_etiqueta[] ({valor, rotulo}), limites: {texto: 4096, legenda: 1024, arquivo_bytes: 26214400, nota: 2000, apelido: 60, lembrete: 200}}` |
| GET | `etiquetas/` | — | `[{id, nome, cor}]` (ativas) |
| GET | `respostas-rapidas/` | — | `[{id, atalho, titulo, texto}]` (ativas; texto com marcadores) |
| GET | `aberturas/` | — | `[{chave, titulo, texto, usa_nome, disponivel}]` (`disponivel` = aprovada pela Meta) |
| GET | `atendentes/` | — | `[{id, nome}]` (quem tem `acessar_crm`) |
| GET | `clientes/` | `?busca=` (CPF ou nome, mín. 3) `&conversa=<id>` (exclui os já vinculados) | `{results: [{id, nome, cpf, telefone}], busca_curta}`. Exige também `vendas.view_cliente` (senão 403) |
| GET | `conversas/` | `?fila=minhas\|sem_dono\|automatico\|todas` (padrão `minhas`) `&situacao=` `&etiqueta=<id>` `&nao_lidas=true` `&busca=` (nome, apelido, telefone, cliente vinculado, texto com 3+ letras) `&ordenar=recentes\|espera` `&page` `&page_size` | paginada de **ConversaItem** + `"contadores": {"minhas": 3, "sem_dono": 5, "automatico": 40, "todas": 48}`. Valor inválido → 400 |
| GET | `conversas/{id}/` | — | **ConversaDetalhe**. Não marca como lida |
| POST | `conversas/{id}/ler/` | — | **ConversaEstado**. Zera `nao_lidas` e agenda o recibo de leitura (tiques azuis). Chame ao abrir a conversa e, com ela aberta e a aba visível, a cada `mensagem_nova` dela |
| GET | `conversas/{id}/mensagens/` | `?antes=<id da mais antiga já carregada>` `&limite=` (1–100, padrão 50) | `{results: [Mensagem] (cronológica), tem_mais_antigas, proximo_cursor}`. `antes` de outra conversa → 400 |
| POST | `conversas/iniciar/` | `{telefone: "(91) 98888-1111", modelo: "<chave>", nome?: "João", conta?: 123}` | 201 **ConversaEstado** (assumida por quem iniciou). Abertura inexistente/não aprovada → 409. Com `conta` (Pagamento de contas a receber, mesmo escopo de lojas): vincula o cliente, usa o primeiro nome dele se `nome` vier vazio e preenche `{valor}`/`{vencimento}` com a parcela em aberto mais antiga, liberando as aberturas de cobrança; conta fora do escopo → 404 |
| GET | `contas/{id}/abertura/` | — | `{cliente: {id, nome}, parcela: {numero, valor, vencimento, vencida} \| null, telefones: [{rotulo, telefone, telefone_formatado, conversa: {id, janela_aberta, assumida_por} \| null}], aberturas: [{chave, titulo, texto (preenchido), cobranca, disponivel}]}`. Não cria conversa. Escopo de lojas de contas a receber (`can_view_all_payments`) → 404 fora dele |

### Ações sobre a conversa (POST, respondem **ConversaEstado**)

| Caminho | Corpo | Regras (409) |
|---|---|---|
| `conversas/{id}/assumir/` | — | com outro dono → 409 `OUTRO_DONO` (use puxar) |
| `conversas/{id}/puxar/` | `{de?: <id do dono que a tela mostrava>}` | sem dono, já é sua, ou o dono mudou. **Auditado** (`crm_conversa_puxada`) |
| `conversas/{id}/atribuir/` | `{usuario: <id>}` | só o dono (repassa) ou quem gerencia; destino precisa ter acesso ao CRM; usuário inexistente → 400. **Auditado** |
| `conversas/{id}/devolver/` | — | volta ao automático; só dono, sem dono ou quem gerencia |
| `conversas/{id}/situacao/` | `{situacao: "ABERTA"\|"PENDENTE"\|"RESOLVIDA", devolver_automatico?: true}` | devolver só ao resolver; se a devolução for recusada, a situação não muda |
| `conversas/{id}/etiquetas/` | `{etiquetas: [1, 4]}` (conjunto completo; `[]` limpa) | etiqueta inexistente ou desativada |
| `conversas/{id}/apelido/` | `{apelido: "Dona Maria"}` (vazio remove; até 60) | — |
| `conversas/{id}/abrir/` | `{modelo: "<chave>", nome?: "Maria"}` | janela aberta: só assume. Fechada: envia o template e assume. Antispam: já saiu abertura nas últimas 24 h sem resposta → 409; nome obrigatório se a abertura usa `{nome}` e o contato não tem nome |
| `conversas/{id}/lembrete/` | `{lembrete_em: "2026-11-24T09:00", texto?: "Ligar", para?: <id>}` | data no passado; destino sem acesso ao CRM |
| `conversas/{id}/lembrete/concluir/` | — | — |

`vincular-cliente/` e `desvincular-cliente/` (POST `{cliente: <id>}`) respondem o **painel**
(`{clientes, sugeridos}`). Vincular só clientes das lojas do usuário (senão 409). **Auditados**
(`crm_cliente_vinculado` / `crm_cliente_desvinculado`).

### Envio

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| POST | `conversas/{id}/enviar/` | JSON `{texto, responde_a?}` ou **multipart** `arquivo` (até 25 MB, tipo pelo conteúdo) + `texto` (legenda até 1024; áudio sem legenda) + `responde_a?` + `voz=1` (áudio gravado) | 201 **Mensagem**. Texto sai na hora (`ENVIADO`, ou `ERRO` com `erro` se a Meta recusar). Arquivo volta `PENDENTE` e sai em segundo plano |
| POST | `conversas/{id}/digitando/` | — | 204 (no máximo a cada 15 s; silencioso se não puder responder) |
| POST | `mensagens/{id}/reenviar/` | — | **Mensagem** (só `SAIDA` com `ERRO`; abertura sai de novo como template) |
| POST | `mensagens/{id}/reagir/` | `{emoji: "👍"}` (vazio remove) | **Mensagem** (últimos 30 dias; exige poder responder) |
| GET | `conversas/{id}/resumo-pagamentos/` | `?cliente=<id>` | `{texto, avisos: []}` — texto pronto (negrito com `*`) para revisar e enviar. Exige `vendas.view_pagamento` (403) e cliente nas lojas do usuário (409) |
| GET | `conversas/{id}/respostas-rapidas/{resposta_id}/previa/` | — | `{texto, avisos}` com `{primeiro_nome}`, `{nome_cliente}`, `{empresa}`, `{atendente}` preenchidos; sem valor → `avisos: ["Sem valor para: nome_cliente"]` |

Trava de resposta (texto, arquivo, reação, reenvio, programada): conversa em `HUMANO`, você é o
dono e a janela de 24 h está aberta. Senão 409 com `motivo`.

### Notas e programadas

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| POST | `conversas/{id}/notas/` | `{texto}` (até 2000) | 201 nota |
| POST | `conversas/{id}/notas/{nota_id}/apagar/` | — | 204. Só quem escreveu (409); automáticas não |
| POST | `conversas/{id}/programadas/` | `{texto, enviar_em}` (5 min a 30 dias à frente; exige poder responder agora) | 201 programada |
| POST | `programadas/{id}/cancelar/` | — | programada `CANCELADA` (409 se já saiu ou foi cancelada) |

### Mídia

`GET mensagens/{id}/arquivo/[?versao=miniatura]` — arquivo do storage privado (use direto em
`<img>`, `<audio>`, `<video>`, mesma origem com o cookie). Abrir o **original grava `LogAcessoMidia`**
(usuário, IP real, user agent); a miniatura (JPEG) não. Miniatura só existe nas mídias recebidas (`tem_miniatura`); nas enviadas, `url_miniatura` é `null`. `Range: bytes=a-b` → **206** com
`Content-Range` (áudio e vídeo). Com S3: **302** para URL assinada de 5 minutos (inclua o domínio
do S3 em `img-src`/`media-src` da CSP). SVG/HTML só como download. Sem mídia pronta → 404.

## Configuração (`crm.gerenciar_crm`)

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| GET | `configuracao/` | — | `{configuracao: {nome_empresa, boas_vindas_ativa, mensagem_boas_vindas, retorno_automatico_horas, autoatendimento_ativo, url_publica, razao_social, cnpj, email_privacidade, atualizado_em}, integracao: {modo_real, itens: [{variavel: "WHATSAPP_TOKEN", descricao, ok}], transcricao, api_version, webhook_url, privacidade_url}, simulado}`. Nunca expõe valores das credenciais |
| PATCH | `configuracao/` | só os campos alterados (validação do `ConfiguracaoForm`: horas ≤ 720, CNPJ com 14 dígitos, URL `https://`) | igual ao GET. **Auditado** com os campos alterados |
| GET/POST | `configuracao/etiquetas/` | POST `{nome, cor, ordem?, ativo?}` (nome único sem diferenciar maiúsculas) | paginada / 201 `{id, nome, cor, cor_display, ordem, ativo}` |
| GET/PATCH | `configuracao/etiquetas/{id}/` | campos parciais | etiqueta. **Não se exclui**: `{ativo: false}` |
| GET/POST | `configuracao/respostas-rapidas/` | POST `{atalho, titulo, texto, ordem?, ativo?}` (atalho sem `/`, minúsculo, único) | paginada / 201 `{id, atalho, titulo, texto, ordem, ativo, criado_por}` |
| GET/PATCH | `configuracao/respostas-rapidas/{id}/` | campos parciais | resposta rápida (não se exclui) |
| GET/POST | `configuracao/aberturas/` | POST `{titulo (3–60), corpo (até 1024; `{nome}` no máx. 1 vez, nem no início nem no fim)}` → vai à Meta | paginada / 201 abertura |
| GET/PATCH | `configuracao/aberturas/{id}/` | `{titulo?, ordem? (0–1000), ativo?, corpo?}` — corpo diferente da última versão = versão nova na Meta (a vigente vale até a decisão) | abertura. 409 se já há versão em análise ou título repetido |
| POST | `configuracao/aberturas/{id}/verificar/` | — | abertura (consulta a Meta agora) |
| POST | `configuracao/aberturas/{id}/simular/` | `{status: "APROVADO"\|"REJEITADO"}` | abertura. Só no modo simulado (409 com credenciais) |
| GET | `configuracao/simulador/` | — | `{disponivel, conversas: [{id, nome_exibicao, telefone}]}` |
| POST | `configuracao/simulador/receber/` | `{telefone, nome?, texto}` | 201 `{conversa_id, mensagem}` (mensagem do cliente; a resposta automática aparece em `conversas/{id}/mensagens/`). 409 com credenciais |
| POST | `configuracao/simulador/ler/` | `{conversa: <id>}` | `{alteradas}` (o cliente "leu" as enviadas) |

Abertura:
```json
{"id": 1, "chave": "retomar-contato", "titulo": "Retomar contato", "ordem": 0, "ativo": true,
 "vigente": {"versao": 1, "corpo": "Olá {nome}, ...", "status": "APROVADO", "status_display": "Aprovado",
             "motivo": "", "erro": "", "nome_meta": "abertura_retomar_contato", "criado_em": "..."},
 "em_analise": null, "ultima": {"versao": 1, "...": "..."}}
```
Status da versão: `ENVIANDO`, `EM_ANALISE`, `APROVADO`, `REJEITADO` (com `motivo`), `PAUSADO`, `DESATIVADO`, `ERRO_ENVIO`, `DESCARTADO`.

## Tempo real

Pelo WebSocket existente (`/ws/notifications/`), todo usuário com `acessar_crm` recebe, depois do commit:

```json
{"event": "crm.evento", "tipo": "mensagem_nova", "conversa_id": 123, "para_mim": true}
```

`para_mim` = a conversa está na fila sem dono ou é sua. O evento não leva conteúdo (LGPD): a SPA
busca pela API. Invalidação sugerida (agrupe eventos em ~400 ms):

| `tipo` | Quando | Invalidar |
|---|---|---|
| `mensagem_nova` | cliente mandou mensagem | `conversas/` (lista e contadores); se for a aberta: `conversas/{id}/mensagens/` (primeira página) e `conversas/{id}/`; com a aba visível, `POST ler/` |
| `mensagem_status` | Meta mudou o status de uma enviada (entregue, lida, erro) | `conversas/{id}/mensagens/` se for a aberta |
| `conversa_atualizada` | posse, situação, etiquetas, apelido, notas, lembrete, programadas, envio da equipe, reação | `conversas/`; se for a aberta: `conversas/{id}/` e `conversas/{id}/mensagens/` |
| `transferencia` | automático passou para a fila da equipe | `conversas/` (pode tocar aviso se `para_mim`); se aberta: `conversas/{id}/` |
| `atribuida` | puxada ou atribuída | `conversas/`; se aberta: `conversas/{id}/` |

Além disso, puxar/atribuir, lembrete vencido e programada que falhou geram **notificação no sino**
(evento `send_notification` com `type_notification: "crm"`; `target_url` aponta para a tela antiga
`/crm/conversas/{id}/` — a SPA deve mapear para a própria rota). `ler/` não emite evento: depois de
chamá-lo, invalide a sua própria lista. Com o WebSocket fora, faça polling de 30 s só com a aba
visível (lista + conversa aberta). Com a conversa rolada para cima, não force a rolagem: mostre
"Novas mensagens".

## Central de cobrança (`/api/bo/v1/crm/cobranca/`)

Painel da régua automática de avisos de cobrança (templates de utilidade da Meta) e dos **disparos
manuais**. Mesmas convenções do resto do contrato (sessão + CSRF, erros `{"erro": {...}}`, paginação
`{count, page, page_size, total_pages, results}`, datas ISO no fuso do sistema, dinheiro como texto
decimal, tag `bo-crm`). Regras em `crm/services/central_cobranca/*` e `crm/services/cobranca.py`.

**Permissões:** leitura (`saude/`, `agenda/`, `historico/`, `modelos/`, `disparos/` GET) = `crm.acessar_crm`;
escrita (`configuracao/`, `pausar/`, `retomar/`, criar/confirmar/cancelar/retomar disparo) = `crm.gerenciar_crm`
(junto com `acessar`). `configuracao/` exige `gerenciar_crm` também no GET. Sem permissão → `403 proibido`.
Toda escrita é **auditada** (`RegistroAuditoria`): `crm_cobranca_configuracao_alterada` (com `campos`),
`crm_cobranca_pausada` / `crm_cobranca_retomada` (com `motivo`), `crm_disparo_previa`, `crm_disparo_confirmado`,
`crm_disparo_cancelado`, `crm_disparo_retomado`.

**Escopo de lojas:** as **listas de clientes** (itens da agenda de um dia, histórico e seu resumo,
destinatários de um disparo) só trazem clientes que o usuário vê nos relatórios de cobrança
(`vendas.view_cliente` + lojas do usuário, ou todas com `view_all_analise_credito`/`can_view_all_stores`).
Sem `vendas.view_cliente` essas listas vêm vazias. Os **totais da agenda** (por dia/etapa) e os contadores
de um disparo são da régua/disparo inteiros (são um só para a empresa). O público de um disparo é montado
só com clientes das lojas de quem cria.

**Telefone:** sempre mascarado — `"(91) *****-0000"` (DDD + 4 últimos). Vazio quando não há número válido.
Número de **referência nunca recebe** aviso (nem aparece como telefone de envio).

### Regras que a tela deve explicar

| Regra | Detalhe |
|---|---|
| Janela de envio | De `cobranca_hora_envio` (padrão 09:00) até **20:00**, hora local. Nada sai em **domingo** nem **feriado** nacional (fixos + Sexta-feira Santa). Vale para régua e disparos. |
| Teto (janela de 24 h) | `efetivo = min(automático, configurado)`, contado nas **últimas 24 h** (janela móvel, como a Meta conta — não por dia do calendário). Automático = **80%** do limite do número na Meta (`TIER_250`→200, `TIER_1K`→800, `TIER_2K`→1600, `TIER_10K`→8000, `TIER_100K`→80000, `TIER_UNLIMITED`→800000). `cobranca_teto_diario` vazio = automático; preenchido só **baixa** o teto. Sem leitura da Meta: última leitura conhecida; sem nenhuma: **200**. Leitura da Meta guardada por 10 min. |
| O que conta no teto | Todo template iniciado pela empresa nas últimas 24 h: avisos da régua, envios de disparos, mensagens de abertura e compra confirmada (sem as recusadas pela Meta). Cada aviso de cobrança confere o teto de novo na hora de gravar, numa transação travada: régua e disparos, mesmo em processos diferentes, nunca passam do teto juntos. |
| Vaga da régua | Os disparos só usam `teto − o que a régua ainda vai mandar hoje` (`teto.reserva_regua_hoje`, calculado pela agenda). A régua tem prioridade; o aviso "no dia do vencimento" só vale no próprio dia. |
| Pausa por qualidade | `quality_rating` **YELLOW** ou **RED** pausa a régua **e** os disparos até a Meta voltar a GREEN (`regua.status = "pausada_por_qualidade"`). |
| Pausa de segurança | Se a leitura da Meta falha **e** a última leitura boa tem mais de **1 h** (ou nunca houve), régua e disparos param (`regua.status = "sem_leitura_recente"`, `numero.pausa`). Uma falha passageira com leitura recente não pausa (vale a última leitura). No modo simulado não há pausa. Os alertas internos para a equipe continuam rodando em qualquer pausa. |
| Pausa manual | `pausar/` e `retomar/` ligam/desligam `cobranca_ativa`. **Pausar a régua não pausa os disparos**: cada disparo confirmado continua até concluir; para parar um disparo, use o `cancelar/` dele. Retomar não muda `cobranca_ativada_em`: a data da primeira ativação continua valendo. |
| Um aviso por dia | Cada cliente recebe no máximo **um** aviso por dia (régua + disparos). |
| Disparo | Ninguém que recebeu aviso (régua ou disparo) nas **últimas 48 h**; ritmo de **20 envios por minuto** (somando todos os disparos); o que não couber no teto continua depois; **5 recusas seguidas** da Meta pausam o disparo (`PAUSADO`, com `motivo_pausa`); se a mensagem for trocada, pausada ou desativada na Meta depois da prévia, o disparo pausa e **não pode ser retomado** (crie outro); **3 dias** depois da confirmação o que não saiu expira (`IGNORADO` com `disparo_expirado`) e o disparo fica `CONCLUIDO`. |
| Escopo dos disparos | Quem vê todas as lojas (`view_all_analise_credito`/`can_view_all_stores`) vê e mexe em todos os disparos; os demais só nos que criaram (os outros respondem `404`). |
| Custo estimado | **R$ 0,035** por mensagem (`custo_por_mensagem`). Estimativa, não é a fatura da Meta. |

### Motivos (códigos estáveis; o `*_display`/`rotulo` traz o texto pronto)

| Código | Onde | Significado |
|---|---|---|
| `bom_pagador` | agenda | Sempre pagou em dia: pula o lembrete "antes" (opção `cobranca_pular_bom_pagador`) |
| `pagamento_informado` | agenda, disparo | Cliente informou pagamento, aguardando baixa |
| `ja_avisado_hoje` | agenda | Já recebe outro aviso no dia |
| `limite_diario` | agenda, `situacao_envio` | Sem vaga no teto das últimas 24 h (nos disparos: descontada a vaga da régua) |
| `sem_telefone_valido` | agenda, disparo | Sem número utilizável |
| `so_referencia` | agenda, disparo | Só tem número de referência (nunca recebe) |
| `antes_da_ativacao` | agenda (bloqueio do dia) | Dia anterior à data de ativação da régua |
| `regua_pausada` | agenda (bloqueio do dia) | `cobranca_ativa = false` |
| `pausada_por_qualidade` | agenda, `situacao_envio` | Qualidade YELLOW/RED na Meta |
| `sem_leitura_recente` | agenda, `situacao_envio` | Pausa de segurança: Meta sem resposta e última leitura com mais de 1 h |
| `domingo_feriado` | agenda, `situacao_envio` | Domingo ou feriado |
| `fora_do_horario` | agenda (hoje depois das 20h), `situacao_envio` | Fora da janela de envio |
| `etapa_sem_modelo` | agenda | Etapa sem mensagem aprovada pela Meta (a régua pula a etapa) |
| `aviso_recente_48h` | disparo | Recebeu aviso nas últimas 48 h |
| `mesmo_cliente` | disparo | O cliente já recebe por outra parcela (uma mensagem por cliente: a de vencimento mais antigo) |
| `parcela_paga` | disparo (no envio) | Parcela paga depois da prévia |
| `parcela_indisponivel` | disparo (no envio) | Parcela saiu do crediário em aberto (quitada, desativada, devolução) |
| `recusado_pela_meta` | disparo (no envio) | A Meta recusou o envio |
| `disparo_expirado` | disparo (no envio) | Mais de 3 dias desde a confirmação: não sai mais |
| `nao_enviado` | disparo (no envio) | Não foi possível montar ou enviar a mensagem (ex.: texto com parâmetro inválido) |

Etapas da régua (`etapa`): `quitacao`, `antes` (3 a 1 dia antes), `dia` (no vencimento), `apos` (2–3 dias
depois, pede comprovante), `insistencia` (repetição sem retorno). No histórico há também `disparo`.

### Saúde do número

`GET cobranca/saude/[?atualizar=true]` (`acessar_crm`; `atualizar=true` lê a Meta agora em vez do cache de 10 min)

```json
{"numero": {"limite_tier": "TIER_2K", "limite_meta": 2000, "qualidade": "GREEN", "qualidade_display": "Alta",
            "fonte": "meta", "lido_em": "2026-11-27T10:00:00-03:00", "leitura_falhou": false, "pausa": "", "pausa_display": ""},
 "teto": {"automatico": 1600, "configurado": null, "efetivo": 1600, "enviados_24h": 37, "restante_agora": 1563,
          "reserva_regua_hoje": 40, "vagas_disparos": 1523},
 "regua": {"status": "ativa", "status_display": "Ativa", "ativa": true, "ativada_em": "2026-11-20T09:00:00-03:00",
           "hora_envio": "09:00", "fim_envio": "20:00",
           "proxima_janela": {"inicio": "2026-11-27T09:00:00-03:00", "fim": "2026-11-27T20:00:00-03:00"},
           "enviando_agora": true},
 "disparos": {"em_andamento": 1, "situacao_envio": "", "situacao_envio_display": ""},
 "custo_por_mensagem": "0.035", "simulado": false}
```
- `fonte`: `meta` (leitura atual) | `ultima_leitura` (Meta fora; vale a última leitura gravada) | `padrao` (nunca leu: teto 200). `qualidade`: `GREEN` | `YELLOW` | `RED` | `""` (desconhecida; `qualidade_display` = "Desconhecida"). `limite_meta` é `null` sem leitura.
- `numero.pausa`: `""` | `pausada_por_qualidade` | `sem_leitura_recente` (com `pausa_display`). `leitura_falhou`: a última tentativa de ler a Meta deu erro.
- `teto.enviados_24h`: templates da empresa nas últimas 24 h; `restante_agora` = efetivo − enviados_24h; `reserva_regua_hoje` = avisos que a régua ainda vai mandar hoje; `vagas_disparos` = restante_agora − reserva_regua_hoje.
- `regua.status`: `ativa` | `pausada` (manual) | `pausada_por_qualidade` | `sem_leitura_recente` | `antes_da_ativacao` (ligada com data futura em `ativada_em`).
- `proxima_janela`: a janela em curso ou a próxima (`null` se não houver nos próximos 14 dias).
- `enviando_agora`: régua ativa, dentro da janela, sem pausa e com teto sobrando.
- `disparos.situacao_envio`: `""` (disparos saindo) ou `fora_do_horario` | `domingo_feriado` | `pausada_por_qualidade` | `sem_leitura_recente` | `limite_diario`.
- `simulado`: sem credenciais da Meta (nada sai de verdade).

### Configuração da régua (`gerenciar_crm`)

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| GET | `cobranca/configuracao/` | — | **CobrancaConfig** |
| PATCH | `cobranca/configuracao/` | só os campos alterados (abaixo) — validação do `CobrancaForm` das telas | **CobrancaConfig**. Ligar (`cobranca_ativa: true`) pela primeira vez marca `cobranca_ativada_em`. Auditado com os campos alterados |
| POST | `cobranca/pausar/` | `{motivo?}` (até 255) | **Saúde**. Já pausada → `409` "A régua já está pausada." |
| POST | `cobranca/retomar/` | `{motivo?}` | **Saúde**. Já ativa → `409` "A régua já está ativa." |

Campos aceitos no PATCH: `cobranca_ativa` (bool), `cobranca_hora_envio` (`"HH:MM"`), `cobranca_pular_bom_pagador`
(bool), `cobranca_intervalo_dias` (1–30), `cobranca_max_insistencias` (0–20), `cobranca_teto_diario` (1–100000
ou `null` = automático), `modelo_aviso_antes`, `modelo_aviso_dia`, `modelo_aviso_apos`, `modelo_aviso_insistencia`,
`modelo_aviso_quitacao`, `modelo_compra_confirmada` (id de mensagem de abertura **ativa** ou `null` = etapa desligada).
Erro → `400 validacao` com `campos` (ex.: `{"cobranca_teto_diario": ["Use de 1 a 100000 mensagens, ou deixe vazio (automático)."]}`).

**CobrancaConfig**
```json
{"configuracao": {"cobranca_ativa": true, "cobranca_ativada_em": "2026-11-20T09:00:00-03:00",
                  "cobranca_hora_envio": "09:00", "cobranca_pular_bom_pagador": true, "cobranca_intervalo_dias": 5,
                  "cobranca_max_insistencias": 3, "cobranca_teto_diario": null,
                  "modelo_aviso_antes": 3, "modelo_aviso_dia": 3, "modelo_aviso_apos": 4, "modelo_aviso_insistencia": 4,
                  "modelo_aviso_quitacao": 5, "modelo_compra_confirmada": null},
 "etapas": [{"campo": "modelo_aviso_antes", "rotulo": "3 dias antes do vencimento",
             "modelo": {"id": 3, "titulo": "Lembrete"}, "pronta": true}],
 "modelos": [{"id": 3, "titulo": "Lembrete", "pronto": true}],
 "limites": {"intervalo_dias_max": 30, "insistencias_max": 20, "teto_diario_max": 100000}}
```
`etapas[].pronta` = a mensagem escolhida tem versão aprovada pela Meta (senão a régua pula a etapa).
`modelos` = mensagens de abertura ativas para os selects (`pronto` = aprovada).

### Agenda da régua (projeção, só leitura)

Simula as rodadas de hoje e dos próximos dias com **as mesmas funções de seleção da rotina** (mesma ordem:
quitação, antes, dia, depois, insistência; um aviso por cliente por dia; teto). O que fica de fora por
bloqueio passageiro (domingo, teto, régua pausada) volta a ser candidato no dia seguinte, como na rotina.
Para **hoje**, só mostra o que **ainda vai sair** (o que já saiu está em `etapas[].enviados` e no histórico),
e `capacidade` é o que resta do teto na janela de 24 h agora; nos dias seguintes, o teto inteiro (estimativa).
A agenda fica até **5 min** em cache (mudar a configuração ou pausar/retomar a recalcula). Pagamentos futuros (quitações) e respostas futuras não são previstos;
os disparos manuais não entram na agenda (estão em `disparos/`).

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| GET | `cobranca/agenda/` | `?dias=` (0–14, padrão 7: hoje + 7 dias) | **Agenda** |
| GET | `cobranca/agenda/{AAAA-MM-DD}/` | `?etapa=quitacao\|antes\|dia\|apos\|insistencia` `&situacao=previsto\|excluido` `&motivo=<código>` `&page` `&page_size` | paginada de **ItemAgenda** + `"resumo": DiaAgenda`. Data fora de hoje…hoje+14 ou inválida → `400` (`campos.data`) |

**Agenda**
```json
{"gerado_em": "2026-11-27T10:00:00-03:00", "teto_efetivo": 1600, "custo_por_mensagem": "0.035",
 "totais": {"previstos": 120, "custo_estimado": "4.20"},
 "dias": [{"data": "2026-11-27", "dia_semana": "sexta-feira", "bloqueio": "", "bloqueio_display": "",
           "capacidade": 1563, "previstos": 42, "excluidos": 7, "custo_estimado": "1.47",
           "etapas": [{"etapa": "antes", "rotulo": "Antes do vencimento", "previstos": 10, "excluidos": 2,
                       "custo_estimado": "0.35", "enviados": 3}],
           "motivos": [{"motivo": "bom_pagador", "rotulo": "Bom pagador (sem lembrete antecipado)", "quantidade": 2}]}]}
```
- `dias[].etapas` vem sempre com as 5 etapas, nesta ordem: `quitacao`, `antes`, `dia`, `apos`, `insistencia`. `enviados` só tem valor hoje.
- `bloqueio` ≠ `""` → nada sai no dia (`domingo_feriado`, `regua_pausada`, `antes_da_ativacao`, `pausada_por_qualidade`, `sem_leitura_recente`, `fora_do_horario`); os candidatos aparecem como excluídos com esse motivo.

**ItemAgenda**
```json
{"parcela_id": 81, "cliente": {"id": 7, "nome": "Maria Souza"},
 "parcela": {"id": 81, "numero": 3, "valor": "100.00", "vencimento": "2026-11-30"},
 "etapa": "antes", "etapa_display": "Antes do vencimento", "situacao": "previsto", "motivo": "", "motivo_display": "",
 "telefone": "(91) *****-0000"}
```

### Histórico

`GET cobranca/historico/` (`acessar_crm`) — avisos da régua e envios de disparos, do mais recente ao mais antigo.

Filtros: `?desde=AAAA-MM-DD` (padrão: 30 dias antes de `ate`) `&ate=AAAA-MM-DD` (padrão: hoje; período máx. 366 dias)
`&etapa=antes|dia|apos|insistencia|quitacao|disparo` `&resultado=<Resultado>` `&status=enviando|enviado|entregue|lido|falhou`
`&disparo=<id>` `&page` `&page_size`. Inválido → `400` com `campos`.

Resposta: paginada de **ItemHistorico** + `"resumo": {"total", "por_etapa": {"antes": 10, "disparo": 4},
"por_status": {"falhou": 1, "enviando": 0, "enviado": 3, "entregue": 6, "lido": 4}, "por_resultado": {"ENVIADO": 9, "RESPONDEU": 5}}`
(resumo do período filtrado inteiro, não só da página).

**ItemHistorico**
```json
{"id": 300, "criado_em": "2026-11-27T09:15:00-03:00", "cliente": {"id": 7, "nome": "Maria Souza"},
 "parcela": {"id": 81, "numero": 3, "valor": "100.00", "vencimento": "2026-11-30"},
 "etapa": "antes", "etapa_display": "Lembrete antes do vencimento", "origem": "regua", "disparo_id": null,
 "telefone": "(91) *****-0000", "status": "lido", "status_display": "Lido",
 "resultado": "RESPONDEU", "resultado_display": "Cliente respondeu", "respondido_em": "2026-11-27T09:40:00-03:00",
 "conversa_id": 12}
```
- `status` vem da mensagem (webhook da Meta): `enviando` → `enviado` → `entregue` → `lido`; `falhou` = recusada/não entregue (inclui resultado `FALHOU`, `SEM_WHATSAPP`, `INVALIDO`).
- `resultado`: `ENVIADO` (sem resposta), `RESPONDEU`, `FALHOU`, `SEM_WHATSAPP`, `INVALIDO`… (`TentativaContato.Resultado`). Vira `RESPONDEU` quando o cliente escreve na conversa.
- `origem`: `regua` | `disparo` (com `disparo_id`). `parcela` pode ser `null`. `conversa_id` abre a conversa no CRM (`conversas/{id}/`).

### Disparos manuais

**Fluxo:** `POST cobranca/disparos/` gera a **prévia** (`PREVIA`, nada é enviado) → a tela mostra totais,
motivos, estimativa, exemplo do texto e destinatários → `POST .../confirmar/` (`AGENDADO`) → a rotina do
worker envia a cada minuto (`ENVIANDO`) → `CONCLUIDO`. `cancelar/` a qualquer momento antes de concluir
(`CANCELADO`; o que já saiu não volta). Recusas seguidas da Meta ou template que deixou de valer → `PAUSADO`
com `motivo_pausa`; `retomar/` volta para `AGENDADO`. Para acompanhar, faça polling de `GET cobranca/disparos/{id}/`
(ex.: a cada 10 s, com a aba visível, enquanto `AGENDADO`/`ENVIANDO`).

**Consistência prévia × envio:** o público é **congelado na prévia** (um item por parcela avaliada). O envio
processa exatamente os itens `PENDENTE`, na ordem, e confere cada um de novo com a mesma regra (pago,
pagamento informado, telefone, 48 h): quem deixou de valer vira `IGNORADO` com o motivo; ninguém novo entra.
Cada item é reservado (`ENVIANDO`) antes de sair, para dois processos nunca enviarem o mesmo item.
A prévia vale **24 h** para ser confirmada; o disparo confirmado vale **3 dias**.

| Método | Caminho | Entrada | Resposta |
|---|---|---|---|
| GET | `cobranca/modelos/` | — | `[{id, titulo, texto, marcadores: ["nome","valor","vencimento"], nome_meta}]` — mensagens ativas com versão vigente aprovada (as que podem ser disparadas) |
| GET | `cobranca/disparos/` | `?status=PREVIA\|AGENDADO\|ENVIANDO\|CONCLUIDO\|CANCELADO\|PAUSADO` (sem filtro: todos menos `PREVIA`) `&page` `&page_size` | paginada de **DisparoItem** (mais recentes primeiro) |
| POST | `cobranca/disparos/` | **PublicoDisparo** (abaixo) | `201` **DisparoDetalhe** (`status = "PREVIA"`) |
| GET | `cobranca/disparos/{id}/` | — | **DisparoDetalhe** |
| GET | `cobranca/disparos/{id}/destinatarios/` | `?situacao=PENDENTE\|ENVIANDO\|ENVIADO\|IGNORADO\|FALHOU\|EXCLUIDO` `&page` `&page_size` | paginada de **Destinatario** (pela ordem) |
| POST | `cobranca/disparos/{id}/confirmar/` | — | **DisparoDetalhe** (`AGENDADO`). `409`: não é prévia, prévia com mais de 24 h, nenhum destinatário, mensagem mudou depois da prévia |
| POST | `cobranca/disparos/{id}/cancelar/` | — | **DisparoDetalhe** (`CANCELADO`). `409` se já concluído/cancelado |
| POST | `cobranca/disparos/{id}/retomar/` | — | **DisparoDetalhe** (`AGENDADO`). `409` se não está `PAUSADO`, se a mensagem mudou/deixou de estar aprovada depois da prévia ou se passou de 3 dias da confirmação |

Id de disparo inexistente ou fora do seu escopo (criado por outra pessoa, se você não vê todas as lojas) → `404 nao_encontrado`.

**PublicoDisparo** — `modelo` (id, obrigatório) + **exatamente um** critério:

| Critério | Campos | Seleção (parcelas do crediário IPX não pagas) |
|---|---|---|
| Atraso | `atraso_min`, `atraso_max` (1–365, mín ≤ máx) | vencidas há entre `atraso_min` e `atraso_max` dias |
| Data de vencimento | `vencimento_data` (`AAAA-MM-DD`) | vencimento nesse dia |
| Dia do vencimento | `vencimento_dia` (`1`, `10` ou `20`) | vencimento na **próxima** ocorrência desse dia (hoje conta) |
| Lista | `parcelas` (`[81, 82]`, até 500 ids) | essas parcelas (ids inexistentes, pagas, fora do crediário ou do escopo vão em `filtros.nao_encontradas`) |

```json
{"modelo": 4, "atraso_min": 5, "atraso_max": 15}
```
Erros: formato (nenhum ou mais de um critério, atraso incompleto, mín > máx, dia ≠ 1/10/20) → `400 validacao`
(mensagem geral ou `campos`); `modelo` inexistente → `400` `campos.modelo`; mensagem inativa/não aprovada,
filtro com mais de 5000 parcelas ou mais de **2000 destinatários** → `409 conflito`.
Cada cliente recebe **uma** mensagem (a parcela de vencimento mais antigo); o template é preenchido com
`{nome}` (primeiro nome), `{valor}` (valor em aberto da parcela) e `{vencimento}` (dd/mm/aaaa).

**DisparoItem** (lista)
```json
{"id": 9, "status": "ENVIANDO", "status_display": "Enviando", "modelo": {"id": 4, "titulo": "Pedido de comprovante"},
 "filtros": {"criterio": "atraso", "atraso_min": 5, "atraso_max": 15},
 "criado_por": {"id": 3, "nome": "Carla"}, "criado_em": "...", "confirmado_em": "...", "concluido_em": null,
 "total": 120, "excluidos": 15, "enviados": 40, "falhas": 1, "ignorados": 2, "percentual": 35, "motivo_pausa": ""}
```
`total` = destinatários da prévia; `percentual` = (enviados + falhas + ignorados) / total.
`filtros.criterio`: `atraso` | `vencimento_data` | `vencimento_dia` | `parcelas` (+ os campos usados e, na lista, `nao_encontradas`).
Status: `PREVIA`, `AGENDADO`, `ENVIANDO`, `CONCLUIDO`, `CANCELADO`, `PAUSADO`.

**DisparoDetalhe** = DisparoItem +
```json
{"versao": {"nome_meta": "abertura_pedido_comprovante", "corpo": "Olá, {nome}! Sua parcela de {valor}..."},
 "confirmado_por": {"id": 3, "nome": "Carla"}, "iniciado_em": "...", "cancelado_por": null, "cancelado_em": null,
 "pendentes": 77,
 "motivos_exclusao": [{"motivo": "aviso_recente_48h", "rotulo": "Recebeu aviso nas últimas 48 h", "quantidade": 9}],
 "motivos_ignorados": [{"motivo": "parcela_paga", "rotulo": "Parcela paga", "quantidade": 2}],
 "custo_estimado": "4.20", "exemplo": "Olá, Maria! Sua parcela de R$ 100,00 venceu em 17/11/2026...",
 "estimativa": {"cabem_hoje": 60, "distribuicao": [{"data": "2026-11-27", "quantidade": 60}, {"data": "2026-11-28", "quantidade": 17}],
                "sem_previsao": 0},
 "situacao_envio": "", "situacao_envio_display": ""}
```
- `estimativa` só em `PREVIA`, `AGENDADO`, `ENVIANDO` e `PAUSADO` (`null` nos demais): reparte os `pendentes`
  pelos próximos dias de envio (até 30) conforme o teto (hoje: o que resta na janela de 24 h; depois, o teto
  inteiro), **menos a reserva da régua** de cada dia (agenda, até 14 dias), e o ritmo de 20/min nas horas
  que restam da janela. Com o número pausado (qualidade ou sem leitura), tudo fica em `sem_previsao`.
  `cabem_hoje` = quantos saem hoje. É estimativa: não considera a expiração de 3 dias.
- `situacao_envio` (mesmos status): por que não está saindo agora (`""` = saindo) — `fora_do_horario`,
  `domingo_feriado`, `pausada_por_qualidade`, `sem_leitura_recente`, `limite_diario`. Vazio nos demais status.
- `exemplo`: o texto como o primeiro destinatário (das lojas que você vê) recebe (`""` se nenhum). `custo_estimado` = `total` × R$ 0,035.
- `pendentes` (inclui os `ENVIANDO`) é 0 num disparo cancelado.

**Destinatario**
```json
{"id": 501, "ordem": 1, "cliente": {"id": 7, "nome": "Maria Souza"},
 "parcela": {"id": 81, "numero": 3, "valor": "100.00", "vencimento": "2026-11-17"},
 "situacao": "ENVIADO", "situacao_display": "Enviado", "motivo": "", "motivo_display": "",
 "telefone": "(91) *****-0000", "processado_em": "...", "conversa_id": 12}
```
`situacao`: `PENDENTE` (na fila), `ENVIANDO` (saindo agora), `ENVIADO`, `IGNORADO` (deixou de valer no envio ou expirou, com `motivo`), `FALHOU`
(`recusado_pela_meta`), `EXCLUIDO` (fora do público já na prévia, com `motivo`). `telefone`: o número usado
(enviados) ou o que receberia (pendentes); vazio nos demais. O status de entrega de cada envio está no
histórico (`historico/?disparo={id}`).

**Por que um item próprio (`ItemDisparo`) e não só `TentativaContato`:** a prévia precisa guardar
excluídos e pendentes, que não são contatos — `TentativaContato` é o histórico de contato usado pelos
relatórios, pela regra de "um aviso por dia" e pela marcação de resposta. Cada envio que **sai** também
grava uma `TentativaContato` (tipo `DISPARO`, `sequencia` = id do disparo; a restrição única
parcela+tipo+sequência continua valendo: uma mensagem por parcela por disparo; `sequencia` passou a
inteiro de 32 bits), então histórico, relatórios, 48 h e "respondeu" funcionam igual aos avisos da régua.
