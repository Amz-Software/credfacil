# CRM de WhatsApp (API oficial da Meta)

Caixa de entrada da equipe para atender clientes pelo WhatsApp oficial (Cloud API),
adaptada de `arquitetura-bot-crm-whatsapp.md`. Backend no app `crm`; tela na SPA
(`front-connect-magic`, rota `/app/crm`).

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

A tela **CRM → Configuração → Integração** mostra o que está faltando, sem expor valores.

## 2. Permissões

| Permissão | Nome no admin | Libera |
|---|---|---|
| `crm.acessar_crm` | Pode acessar o CRM de WhatsApp | Ver e atender todas as conversas |
| `crm.gerenciar_crm` | Pode gerenciar o CRM de WhatsApp | Etiquetas, respostas rápidas, aberturas, configuração, atribuir qualquer conversa |

`gerenciar` só vale junto com `acessar`. Superusuário tem todas (regra do Django).
Na SPA, as flags são `acessos.pode_acessar_crm` e `acessos.pode_gerenciar_crm`, e o
CRM **não** é liberado por `is_admin`/`is_staff`: só pela flag.

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

## 4. API

Base: `/api/crm/`. Autenticação JWT (Bearer). Toda rota exige `crm.acessar_crm`,
salvo indicação. Erros: `400 {campo: [msg]}` ou `{detail}`, `403`, `404`,
`409 {detail}` (regra de negócio, mensagem pronta para mostrar).

### 4.1 Tipos

```ts
type Modo = "AUTOMATICO" | "AGUARDANDO" | "HUMANO";
type Situacao = "ABERTA" | "PENDENTE" | "RESOLVIDA";
type Usuario = { id: number; nome: string };
type Etiqueta = { id: number; nome: string; cor: "CINZA"|"VERMELHO"|"LARANJA"|"AMARELO"|"VERDE"|"AZUL"|"ROXO"|"ROSA"; ordem: number; ativo: boolean };

type ConversaResumo = {
  id: number;
  telefone: string;                 // wa_id, só dígitos (ex.: "5591999990000")
  contato_nome: string;             // nome no perfil do WhatsApp
  apelido: string;                  // nome interno da equipe
  nome_exibicao: string;            // apelido → contato_nome → telefone formatado
  clientes: { id: number; nome: string }[];   // clientes vinculados
  modo: Modo;
  assumida_por: Usuario | null;
  situacao: Situacao;
  ultima_mensagem_em: string | null;           // ISO 8601
  ultima_mensagem_texto: string;               // prévia (até 120 caracteres)
  ultima_mensagem_direcao: "ENTRADA" | "SAIDA" | null;
  nao_lidas: number;
  janela_aberta: boolean;
  janela_expira_em: string | null;
  etiquetas: Etiqueta[];
  lembrete: { em: string; texto: string; para: Usuario | null; vencido: boolean } | null;
  tem_programada: boolean;
  motivo_transferencia: { texto: string; silenciosa: boolean; criado_em: string } | null;
};

type Midia = {
  status: "PENDENTE" | "OK" | "ERRO" | "EXPIRADA";
  mime: string; nome_original: string; tamanho_bytes: number | null;
  duracao_s: number | null; largura: number | null; altura: number | null;
  voz: boolean; tem_miniatura: boolean;
};

type Mensagem = {
  id: number;
  direcao: "ENTRADA" | "SAIDA";
  autor: "CLIENTE" | "AUTOMATICO" | "HUMANO" | "SISTEMA";
  autor_nome: string;               // atendente, "Atendimento automático" ou contato
  tipo: "TEXTO"|"AUDIO"|"IMAGEM"|"VIDEO"|"DOCUMENTO"|"FIGURINHA"|"LOCALIZACAO"|"CONTATO"|"DESCONHECIDO";
  texto: string;                    // corpo, legenda ou transcrição
  status: "RECEBIDO"|"PENDENTE"|"ENVIADO"|"ENTREGUE"|"LIDO"|"ERRO";
  erro: string;                     // motivo legível quando status = ERRO
  origem: "" | "ABERTURA" | "BOAS_VINDAS" | "PROGRAMADA";
  criado_em: string;
  responde_a: { id: number; tipo: string; texto: string; autor: string } | null;
  reacao_cliente: string;           // emoji que o cliente reagiu nesta mensagem ("" = nenhum)
  reacao_equipe: string;            // emoji que a equipe reagiu
  midia: Midia | null;
  dados: {                          // conforme o tipo
    localizacao?: { latitude: number; longitude: number; nome?: string; endereco?: string };
    contatos?: { nome: string; telefones: { numero: string; wa_id?: string }[] }[];
    encaminhada?: boolean;
  };
  transcricao_status: "" | "PENDENTE" | "OK" | "ERRO";
  pode_reenviar: boolean;           // SAIDA com ERRO
};

type Nota = { id: number; texto: string; autor: Usuario | null; automatica: boolean;
              tipo: "GERAL" | "TRANSFERENCIA"; silenciosa: boolean; criado_em: string; pode_apagar: boolean };
type Programada = { id: number; texto: string; enviar_em: string;
                    status: "AGENDADA"|"ENVIANDO"|"ENVIADA"|"CANCELADA"|"ERRO"; criado_por: Usuario | null; erro: string };
type ConversaDetalhe = ConversaResumo & {
  mensagens: Mensagem[];            // últimas 50, da mais antiga para a mais nova (sem reações avulsas)
  tem_mais_antigas: boolean;
  notas: Nota[];                    // até 100, da mais antiga para a mais nova
  programadas: Programada[];        // só AGENDADA
  pode_responder: boolean;          // passa na trava de resposta agora
  bloqueio: null | { motivo: "OUTRO_DONO" | "JANELA_FECHADA" | "NAO_ASSUMIDA"; detail: string };
};
```

### 4.2 Integração e configuração

| Método e rota | Corpo | Resposta | Permissão |
|---|---|---|---|
| `GET integracao/` | — | `{modo: "real"\|"simulado", configurado: {token, phone_number_id, waba_id, app_secret, verify_token, transcricao}: bool, api_version, webhook_url, pendencias: string[]}` | gerenciar |
| `GET configuracao/` | — | `{boas_vindas_ativa, mensagem_boas_vindas, retorno_automatico_horas, nome_empresa, autoatendimento_ativo, url_publica}` | acessar |
| `PATCH configuracao/` | mesmos campos | idem | gerenciar |
| `GET atendentes/` | — | `Usuario[]` (ativos com `acessar_crm`) | acessar |

### 4.3 Conversas

| Método e rota | Corpo / query | Resposta |
|---|---|---|
| `GET conversas/` | `fila=minhas\|sem_dono\|automatico\|todas` (padrão `todas`), `situacao`, `etiqueta=1,2`, `nao_lidas=1`, `lembrete=vencido`, `search`, `ordem=recentes\|espera`, `page` | `{count, next, previous, results: ConversaResumo[]}` (50 por página) |
| `GET conversas/contadores/` | — | `{minhas, sem_dono, automatico, todas, nao_lidas_minhas}` |
| `POST conversas/iniciar/` | `{telefone, modelo, nome?}` | `ConversaDetalhe` (201). Envia a abertura `modelo` e assume. |
| `GET conversas/{id}/` | — | `ConversaDetalhe`. Zera `nao_lidas` e envia o recibo de leitura. |
| `GET conversas/{id}/mensagens/` | `antes=<id>&limite=50` ou `em_torno_de=<id>` | `{results: Mensagem[], tem_mais_antigas}` |
| `GET conversas/{id}/busca/` | `q` (≥ 3 caracteres) | `{mensagem_id, trecho, criado_em, direcao}[]` (até 50) |
| `GET conversas/{id}/painel/` | — | `{clientes: PainelCliente[], sugeridos: {id, nome, telefone}[]}` |
| `GET conversas/{id}/buscar-cliente/` | `q` (CPF ou nome, ≥ 3 caracteres) | `{id, nome, cpf (mascarado), telefone}[]` no escopo de lojas |
| `POST conversas/{id}/resumo-pagamentos/` | `{cliente}` | `{texto}` pronto para o compositor (exige `vendas.view_pagamento`) |
| `POST conversas/{id}/assumir/` | — | `ConversaDetalhe` · 409 se está com outra pessoa |
| `POST conversas/{id}/puxar/` | `{de: user_id}` | `ConversaDetalhe` · 409 se o dono mudou |
| `POST conversas/{id}/atribuir/` | `{usuario}` | `ConversaDetalhe` · o dono atual ou quem gerencia |
| `POST conversas/{id}/devolver/` | — | `ConversaDetalhe` · o dono ou quem gerencia |
| `POST conversas/{id}/situacao/` | `{situacao, devolver_automatico?: bool}` | `ConversaDetalhe` |
| `POST conversas/{id}/etiquetas/` | `{etiquetas: number[]}` (substitui) | `ConversaDetalhe` |
| `PATCH conversas/{id}/apelido/` | `{apelido}` (≤ 60, `""` remove) | `ConversaDetalhe` |
| `POST conversas/{id}/vincular-cliente/` | `{cliente}` | `ConversaDetalhe` |
| `POST conversas/{id}/desvincular-cliente/` | `{cliente}` | `ConversaDetalhe` |
| `POST conversas/{id}/abrir/` | `{modelo, nome?}` | `ConversaDetalhe`. Com a janela aberta só assume. |
| `POST conversas/{id}/enviar/` | `{texto, responde_a?}` | `Mensagem` (201) |
| `POST conversas/{id}/enviar-midia/` | multipart `arquivo`, `legenda?`, `voz?` (`"true"`), `responde_a?` | `Mensagem` (201, `status=PENDENTE`) |
| `POST conversas/{id}/digitando/` | — | `204` |
| `GET/POST conversas/{id}/notas/` | `{texto}` (≤ 2000) | `Nota[]` / `Nota` |
| `DELETE conversas/{id}/notas/{nota_id}/` | — | `204` · só o autor, nota automática não |
| `PUT conversas/{id}/lembrete/` | `{lembrete_em, texto?, para?}` | `ConversaDetalhe` |
| `DELETE conversas/{id}/lembrete/` | — | `ConversaDetalhe` |
| `POST conversas/{id}/programadas/` | `{texto, enviar_em}` (5 min a 30 dias) | `Programada` (201) |
| `POST programadas/{id}/cancelar/` | — | `Programada` |
| `POST conversas/{id}/respostas-rapidas/{rid}/previa/` | — | `{texto, avisos: string[]}` |

`PainelCliente = {id, nome, cpf, telefone, vinculado, solicitacoes: {id, status, status_display, produto, data}[], vendas: {id, data, valor_total, cancelada}[], pagamentos: PagamentoAberto[]}`
`PagamentoAberto = {pagamento_id, venda_id, produto, parcelas_abertas, total_aberto, parcelas_atrasadas, total_atrasado, em_confirmacao, proxima: {numero, valor, vencimento} | null, link_publico}` (vazio sem `vendas.view_pagamento`)
(`id` da solicitação = id do cliente, como na SPA em `/app/solicitacoes/{id}`).

### 4.4 Mensagens

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET mensagens/{id}/arquivo/` | `versao=miniatura` opcional | `{url, expira_em_segundos}` — URL assinada de 1 h, usável direto em `<img src>`/`<a href>` |
| `POST mensagens/{id}/reenviar/` | — | `Mensagem` |
| `POST mensagens/{id}/reagir/` | `{emoji}` (`""` remove) | `Mensagem` |

### 4.5 Cadastros

| Rota | Leitura | Escrita |
|---|---|---|
| `etiquetas/` (CRUD; `DELETE` desativa) | acessar | gerenciar |
| `respostas-rapidas/` (CRUD) `{atalho, titulo, texto, ordem, ativo}` | acessar | gerenciar |
| `aberturas/` (lista, `POST {titulo, corpo}`, `PATCH {titulo?, corpo?, ativo?, ordem?}`) | acessar | gerenciar |
| `POST aberturas/{id}/verificar/` | — | gerenciar |
| `POST aberturas/{id}/simular/ {status: "APROVADO"\|"REJEITADO"}` (só simulado) | — | gerenciar |
| `GET aberturas/disponiveis/` → `{chave, titulo, texto, usa_nome, disponivel}[]` | acessar | — |

Abertura: `{id, chave, titulo, ordem, ativo, vigente: Versao|null, em_analise: Versao|null, ultima: Versao|null}`,
`Versao = {versao, corpo, status: "ENVIANDO"|"EM_ANALISE"|"APROVADO"|"REJEITADO"|"PAUSADO"|"DESATIVADO"|"ERRO_ENVIO"|"DESCARTADO", motivo, erro, nome_meta, criado_em}`.
O corpo aceita o marcador `{nome}` (primeiro nome do cliente), no máximo uma vez.
Respostas rápidas aceitam `{primeiro_nome}`, `{nome_cliente}`, `{empresa}` e `{atendente}`.

### 4.6 Simulador (só com o WhatsApp simulado; permissão gerenciar)

| Rota | Corpo | Efeito |
|---|---|---|
| `POST simulador/receber/` | `{telefone, nome?, texto}` | Grava como se o cliente tivesse escrito |
| `POST simulador/ler/` | `{conversa}` | Marca as mensagens enviadas como lidas |

### 4.7 Tempo real

Pelo WebSocket de notificações já existente (`/ws/notifications/`), quem tem
`acessar_crm` recebe:

```json
{"event": "crm.evento", "tipo": "mensagem_nova" | "conversa_atualizada" | "mensagem_status" | "transferencia" | "atribuida", "conversa_id": 123, "para_mim": false}
```

`para_mim = true` quando a conversa é minha ou está sem dono (usado para tocar o som).
O front também consulta a API periodicamente como reserva.
