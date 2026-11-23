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
| POST | `conversas/iniciar/` | `{telefone: "(91) 98888-1111", modelo: "<chave>", nome?: "João"}` | 201 **ConversaEstado** (assumida por quem iniciou). Abertura inexistente/não aprovada → 409 |

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
