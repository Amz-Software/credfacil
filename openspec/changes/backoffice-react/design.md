# Desenho técnico: novo backoffice em React

## 1. Contexto

O inventário de 2026-11-23 mapeou 185 rotas web do backoffice:

| Tipo | Quantidade |
|---|---|
| Telas autenticadas | 72 |
| Telas públicas | 9 |
| Ações POST | 71 |
| Documentos (PDF, impressão, Excel) | 15 |
| Endpoints AJAX | 18 |

Telas de Estoque, Assistência, Caixa e Caixa Mensal já não existem. O que existe hoje:

- **Regra de negócio** compartilhada entre telas e API em `vendas/services/` (`parcelas`, `venda`, `analise`, `notificacoes`, `kpis`, `lojas`), com `ErroDeNegocio`.
- **API DRF** em `/api/`, com JWT + sessão, usada pela SPA do vendedor. Cobre boa parte de crédito, vendas, produtos, lojas e usuários. **Não cobre:** contas a receber (situações, parcelas, comprovantes, BO, quitação, contatos), relatórios, notificações, dashboard e o CRM inteiro. O CRM devolve trechos de HTML.
- **Tempo real** com Channels + Redis em `/ws/notifications/`, grupo `user_{id}`, campos `event` e `crm_evento`.
- **Escopo de loja** resolvido de quatro jeitos diferentes: sessão, `?loja=`, `user.lojas` e `user.loja`.

## 2. Objetivos / Fora de escopo

**Objetivos**
- Substituir todas as telas autenticadas do backoffice por uma SPA React com padrões únicos de lista, detalhe, formulário e ação.
- Aplicar a paleta da logo com contraste AA, modo claro e escuro.
- Fechar as falhas de segurança atuais (Fase 0) e dar à SPA autenticação por sessão, 2FA, auditoria e autorização centralizada por loja.
- Migrar sem parada: módulo a módulo, com as telas Django como reserva até a paridade.

**Fora de escopo**
- A SPA do vendedor (`front-connect-magic`) continua como está, recebendo só os ajustes de compatibilidade da Fase 0.
- As páginas públicas do cliente continuam no Django: consulta de pagamentos, pagamento, privacidade, foto pelo celular e e-mails de senha.
- O `/admin/` do Django continua como ferramenta de suporte e fica restrito a superusuários.
- Não muda nenhuma regra de cálculo (financiamento, parcelas, repasse), nem modelos de venda, análise ou parcela.

## 3. Stack da SPA

| Camada | Escolha | Por quê |
|---|---|---|
| Base | React 19 + TypeScript (strict) + Vite | Mesma família da SPA do vendedor, em versões atuais |
| Rotas | TanStack Router | Rotas e **parâmetros de busca tipados e validados com zod**: filtros de lista na URL sem parse manual (são dezenas de telas de lista) |
| Dados do servidor | TanStack Query 5 | Cache, invalidação por evento de WebSocket, atualização otimista |
| Tabelas | TanStack Table 8 + TanStack Virtual | Tabela de dados única (ordenação, colunas, seleção); listas longas do CRM virtualizadas |
| Formulários | react-hook-form + zod | Igual à SPA do vendedor |
| UI | Tailwind CSS 4 + shadcn/ui (Radix) + lucide | Componentes acessíveis, tema por tokens CSS |
| Feedback e navegação | sonner (toasts), cmdk (Ctrl+K) | — |
| Gráficos | Recharts (base dos gráficos do shadcn) | Seguir a skill `dataviz` |
| Datas e números | date-fns (pt-BR), `Intl.NumberFormat` | — |
| Estado de interface | Zustand, **só** para menu, tema e preferências | Dado do servidor fica no Query |
| Contrato da API | `openapi-typescript` + `openapi-fetch` gerados do drf-spectacular | Tipos sempre iguais ao backend; a CI acusa divergência |
| Conteúdo rico | Editor.js (modelo de contrato da loja) + DOMPurify | Já usado hoje; o HTML gerado é sempre sanitizado |
| Testes | Vitest + Testing Library + MSW; Playwright (E2E) | — |
| Fonte | Inter variable, hospedada na própria app (`@fontsource-variable/inter`) | Sem CDN, o que deixa a CSP estrita; `tabular-nums` em valores |

Não haverá pacote compartilhado com a SPA do vendedor por enquanto (YAGNI). Os tokens de cor são os mesmos e podem ser levados para lá depois.

## 4. Hospedagem e autenticação

**Decisão:** a SPA fica na **mesma origem** do Django, em `https://<domínio do backoffice>/painel/`. A autenticação é por **cookie de sessão do Django** (HttpOnly) + CSRF. A SPA não usa JWT.

Motivos:
- Nenhum token fica acessível ao JavaScript. Um XSS não rouba a sessão, ao contrário do JWT no localStorage da SPA do vendedor.
- Logout e revogação acontecem no servidor (a sessão é apagada).
- Na migração, o mesmo login vale para as telas Django e para as telas novas, então o usuário navega entre as duas sem perceber.
- O WebSocket autentica pelo cookie (o `AuthMiddlewareStack` já faz isso) e o token não aparece na URL nem nos logs.

Fluxo:
1. `GET /api/bo/v1/auth/csrf/` grava o cookie `csrftoken`. A SPA envia `X-CSRFToken` em toda mutação.
2. `POST /api/bo/v1/auth/login/` recebe `{usuario, senha}`.
   - Se o 2FA for obrigatório, responde `{etapa: "otp"}`. Em seguida, `POST auth/otp/` recebe `{codigo}`.
   - No sucesso, o servidor faz `cycle_key()` da sessão e devolve `me`.
3. `GET /api/bo/v1/me/` devolve o usuário, as permissões efetivas, as lojas permitidas, as flags de interface e a situação do 2FA.
4. `POST /api/bo/v1/auth/logout/` apaga a sessão. `POST auth/sessoes/encerrar-outras/` encerra as outras sessões do usuário.

Regras de sessão:
- Cookie `Secure`, `HttpOnly`, `SameSite=Lax`.
- Expira após **30 min de inatividade** (`SESSION_SAVE_EVERY_REQUEST`) e tem limite absoluto de 12 h.
- A SPA avisa 2 min antes de expirar.

Entrada no backoffice:
- Exige a nova permissão `accounts.acessar_backoffice`. VENDEDOR não tem essa permissão e recebe 403 já no login, com mensagem indicando a SPA de vendas.
- 2FA TOTP com códigos de recuperação (`django-otp`), **obrigatório** para:
  - ADMINISTRADOR;
  - ANALISTA;
  - quem tem permissão de usuários, grupos, repasses ou quitação.
  
  Os demais podem ativar por opção.
- Bloqueio por tentativas com `django-axes`: 5 falhas em 15 min por usuário + IP. Vale para a API do backoffice, o login Django, o admin e o reset de senha.

## 5. API do backoffice (`/api/bo/v1/`)

- **Autenticação:** só `SessionAuthentication` com CSRF. JWT não entra nesse namespace.
- **Permissão:** uma classe por ação, declarada na view. O padrão é negar.
- **Sucesso:**
  - objeto direto;
  - listas paginadas: `{"count", "page", "page_size", "total_pages", "results"}`, com `page_size` de no máximo 100 e padrão 25;
  - ordenação por `?ordenar=-campo`.
- **Erro** (exception handler próprio):
  ```json
  {"erro": {"codigo": "validacao", "mensagem": "Revise os campos destacados.", "campos": {"cpf": ["CPF inválido."]}}}
  ```
  - `codigo` pode ser `validacao`, `nao_autenticado`, `proibido`, `nao_encontrado`, `conflito`, `regra_de_negocio` ou `limite_excedido`.
  - `ErroDeNegocio` vira `regra_de_negocio` (422).
  - Nunca devolve 500 por id inexistente (`get_object_or_404`).
- **Ações:** `POST /recurso/{id}/<acao>/`. Nenhuma mutação aceita GET.
- **Regra de negócio:** fica só em `vendas/services/` e nos serviços do CRM. As views só validam a entrada, chamam o serviço e serializam.
- **Esquema OpenAPI:** servido só para staff. A CI da SPA gera os tipos e falha se houver diferença.
- **Código:** novo app Django `backoffice_api/`, com um módulo por domínio (`credito`, `vendas`, `financeiro`, `lojas`, `catalogo`, `admin`, `relatorios`, `notificacoes`, `crm`) e testes por permissão e papel.

Endpoints novos por domínio (as lacunas da API atual):

| Domínio | Endpoints |
|---|---|
| Crédito | fila com KPIs e contadores; aprovar, reprovar e cancelar **com motivo**; observações; linha do tempo (simple_history + observações); ações de app, iCloud e IMEI do analista; pré-análise (aprovar, reprovar, Serasa) |
| Vendas | lista e detalhe; edição; edição especial; troca; cancelar; documentos; PDFs gerados no servidor (nota, carnê, contrato) |
| Financeiro | contas a receber com filtros de situação; situações (no lugar dos 11 toggles); parcelas (editar, adicionar, vencimento); comprovantes; quitação; contatos; BO (prévia + PDF) |
| Lojas e repasses | lojas; calendário de repasses; repasses (criar, editar, status); números autenticadores |
| Catálogo | produtos, marcas, tipos e parcelamentos |
| Administração | usuários; grupos com matriz de permissões; perfil; 2FA; sessões |
| Relatórios | vendas, solicitações, contas a receber, situações e parcelas, em PDF (WeasyPrint) e Excel; dashboard |
| Notificações | lista, marcar lida, marcar todas |
| CRM | conversas (lista com filtros e contadores, detalhe, mensagens com cursor); ações (assumir, atribuir, devolver, situação, etiquetas, vincular cliente, abertura); envio com mídia; reações; notas, lembretes e programadas; mídia autenticada; configuração (aberturas, etiquetas, respostas) |

## 6. Escopo de loja e autorização

- **Uma função central** `escopo_lojas(request) -> QuerySet[Loja]`, usada por toda view do backoffice:
  - **administrador** (ou quem tem `can_view_all_*`): todas as lojas;
  - **gerente**: lojas em `Loja.gerentes` + lojas em `Loja.usuarios`;
  - **usuário comum**: só lojas em `Loja.usuarios` (e `user.loja`, por compatibilidade).
- **Loja ativa:** a SPA envia o cabeçalho `X-Loja: <id>|todas`. O servidor **sempre** cruza esse valor com `escopo_lojas`:
  - id fora do escopo → 403;
  - `todas` sem permissão global → 403.
  
  A escolha da interface nunca concede acesso por si só.
- **Objetos:** toda consulta por id filtra por `loja__in=escopo`. Um objeto de outra loja responde 404, para não revelar que existe.
- **Interface:** a SPA esconde o que o usuário não pode fazer (a partir de `me.permissoes`), mas isso é só conforto. Os testes do backend cobrem o mesmo cenário sem a interface.

## 7. Design system

### 7.1 Paleta (extraída da logo)

A logo IPIX é amarelo `#FFDD21` + branco (versão para fundo escuro) ou + preto. A logo CredFacil é monocromática. A paleta é **amarelo IPIX + tinta + branco**.

**Amarelo IPIX** (500 é o tom exato da logo):

| 50 | 100 | 200 | 300 | 400 | **500** | 600 | 700 | 800 | 900 | 950 |
|---|---|---|---|---|---|---|---|---|---|---|
| `#FFFCEB` | `#FFF8D1` | `#FFF1A3` | `#FFE970` | `#FFE245` | **`#FFDD21`** | `#F0C300` | `#C29700` | `#8A6600` | `#705000` | `#422E00` |

**Tinta** (neutros a partir do preto da logo):

| 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950 |
|---|---|---|---|---|---|---|---|---|---|---|
| `#F8F8FA` | `#F1F1F4` | `#E4E4EA` | `#C9C9D3` | `#9A9AA8` | `#6B6B7B` | `#4A4A58` | `#2C2C38` | `#1F1F28` | `#16161D` | `#0E0E12` |

**Regras de contraste** (medidas com a fórmula WCAG):
- Amarelo é **preenchimento**, nunca texto sobre branco: amarelo-500 sobre branco dá 1,34:1.
  - Botão primário: fundo amarelo-500 com texto tinta-900 (13,4:1).
  - Destaque textual no modo claro usa amarelo-800 `#8A6600` (5,27:1 sobre branco).
  - No escuro, amarelo-500 sobre tinta-900 dá 13,9:1.
- Texto secundário: tinta-500 sobre branco (5,23:1); no escuro, `#A1A1B0` sobre o fundo (7,3:1).
- Anel de foco:
  - claro: 2 px tinta-900 + halo amarelo-500 de 4 px (amarelo sozinho sobre branco não atinge 3:1);
  - escuro: anel amarelo-500.
- Cores de status **distintas do amarelo da marca**, para "alerta" não parecer "primário":

  | Status | Preenchimento | Texto sobre claro |
  |---|---|---|
  | Sucesso | `#16A34A` | `#15803D` |
  | Perigo | `#DC2626` | `#B91C1C` |
  | Alerta (laranja, não âmbar) | `#EA580C` | `#C2410C` |
  | Informação | `#2563EB` | `#1D4ED8` |

- As 10 situações de cobrança (lembrete, BO, cobrança, sem conexão, roubo, sem contato, mais prazo, bloqueado, desativado, devolução) ganham tokens próprios `--situacao-*`, com a mesma cor na lista e no detalhe, como já acontece hoje.

**Mapeamento dos temas** (tokens CSS no padrão shadcn):

| Token | Claro | Escuro |
|---|---|---|
| `--background` | tinta-50 | tinta-950 |
| `--card` / `--popover` | branco | tinta-900 |
| `--border` / `--input` | tinta-200 | tinta-700 |
| `--foreground` | tinta-900 | tinta-100 |
| `--muted-foreground` | tinta-500 | `#A1A1B0` |
| `--primary` / `--primary-foreground` | amarelo-500 / tinta-900 | amarelo-500 / tinta-900 |
| `--accent` (hover de linha) | amarelo-50 | tinta-800 |
| `--sidebar` | tinta-900 | tinta-950 |
| `--sidebar-ativo` | barra amarelo-500 + fundo tinta-800 + texto branco | idem |

### 7.2 Identidade e tipografia
- **Logos:**
  - menu lateral aberto: logo IPIX branca e amarela (`static/images/IPIX.png`, convertida para SVG);
  - menu recolhido e favicon: o círculo amarelo (`logo.png`);
  - impressos e PDF: versão preta.
- **Login:** tela dividida. Painel tinta-900 com a logo IPIX e a frase "Fácil comprar, fácil pagar"; formulário em fundo claro.
- **Inter:**
  - corpo de 14 px (densidade de backoffice);
  - escala 12, 13, 14, 16, 20, 24, 30;
  - pesos 400, 500 e 600;
  - valores, CPF, IMEI e datas com `tabular-nums`.
- **Raio e sombra:**
  - raio de 10 px (cartões) e 8 px (campos e botões);
  - sombras suaves só em elementos flutuantes (popover, diálogo);
  - cartões usam borda em vez de sombra.
- **Modo escuro** obrigatório e de primeira classe: claro, escuro ou do sistema, com preferência guardada.

### 7.3 Componentes base
Ficam em `components/`, sobre o shadcn:

- `AppShell` (menu, topo, área de conteúdo)
- `PageHeader` (título, trilha, ações)
- `DataTable` (padrão de lista, seção 8.2)
- `FilterBar` com chips de filtro ativo
- `StatusBadge` (status, situação, app)
- `KpiCard`
- `Timeline` (histórico)
- `ConfirmDialog` (com motivo obrigatório quando aplicável)
- `EmptyState`
- `ErrorState`
- `Skeleton`
- `MoneyInput`, `CpfInput`, `PhoneInput`, `ImeiInput`
- `FileDropzone` (prévia + validação de tipo e tamanho)
- `DocumentViewer` (PDF e imagem autenticados)
- `Can` (renderiza o conteúdo só com a permissão indicada)
- `LojaSelect`

## 8. Arquitetura de informação e padrões de uso

### 8.1 Navegação
Menu lateral recolhível, agrupado por domínio. Cada item aparece pela permissão, e o pai aparece se algum filho aparecer.

| Grupo | Itens |
|---|---|
| **Início** | Painel (conteúdo por papel: o analista vê a fila e os prazos, o financeiro vê a inadimplência, o admin vê a visão geral) |
| **Crédito** | Fila de análise (solicitações), Análises rápidas |
| **Vendas** | Vendas, Produtos vendidos |
| **Financeiro** | Contas a receber, Repasses (tela própria; hoje fica escondida no detalhe da loja) |
| **Atendimento** | Conversas (CRM) |
| **Relatórios** | Central única: Vendas, Solicitações, Contas a receber, Situações, Parcelas e Gráficos |
| **Catálogo** | Produtos, Marcas, Tipos, Parcelamentos |
| **Administração** | Lojas, Usuários, Grupos e permissões, Números autenticadores, Configuração do CRM |

Barra superior:
- **Busca global (Ctrl+K):** cliente por nome ou CPF, venda por número, IMEI, e atalhos para telas.
- **Seletor de loja**, que não existe hoje.
- Notificações, tema e menu do usuário (perfil, senha, 2FA, sessões ativas, sair).

### 8.2 Padrões
- **Listas:**
  - filtros na URL (dá para compartilhar o link e voltar para a mesma busca);
  - chips de filtro ativo;
  - ordenação e paginação no servidor;
  - colunas configuráveis, lembradas por usuário;
  - seleção com ações em massa e exportação;
  - linha clicável que abre o detalhe;
  - skeleton enquanto carrega e estado vazio com ação.
- **CPF:** mascarado nas listas (`***.456.789-**`) e completo só no detalhe, por LGPD.
- **Detalhe:**
  - cabeçalho fixo com status e ações primárias;
  - abas;
  - linha do tempo com quem fez o quê e quando;
  - documentos com visualizador interno.
- **Ações:**
  - ações destrutivas ou de decisão (reprovar, cancelar, quitar, edição especial) pedem confirmação e motivo, que vai para a auditoria;
  - nenhuma ação "silenciosa".
- **Formulários:**
  - validação em linha;
  - máscaras;
  - aviso ao sair com alterações não salvas;
  - rascunho local só em formulários longos (cadastro de solicitação).
- **Fila de análise:**
  - ordenada pelo tempo de espera, com cronômetro;
  - atualização em tempo real pelo WebSocket, no lugar do polling de 15 s;
  - atalhos de teclado (J/K navegar, A aprovar, R reprovar);
  - painel lateral com o resumo do cliente sem sair da fila.
- **Contas a receber:**
  - os 11 botões de situação viram um conjunto de etiquetas de situação, com histórico;
  - a edição de parcela abre numa gaveta lateral.
- **Impressos:** nota, carnê, contrato, BO e relatórios passam a ser PDFs gerados no servidor (WeasyPrint, já usado). Isso elimina html2pdf, CDNs e `window.print` com layout variável.
- **Responsividade:** pensada primeiro para desktop, e funcional em tablet (o CRM inclusive).
- **Acessibilidade:** meta WCAG 2.2 AA. Teclado em tudo, foco visível, rótulos e aria nos componentes, sem informação só por cor (status com ícone e texto).

### 8.3 O que não será portado
As inconsistências encontradas no inventário não vão para a SPA:
- rotas mortas (`cliente_edit_form`, `cliente_update_imei_telefone`, `accounts:profile`);
- mutações por GET;
- permissões escritas com nome errado nos templates;
- a chamada ao endpoint inexistente `/info-products/imei/<id>/`;
- templates órfãos.

## 9. Segurança

### 9.1 Fase 0: falhas atuais (conferidas no código em 2026-11-23)

| # | Severidade | Falha | Onde | Correção |
|---|---|---|---|---|
| 1 | CRÍTICA | `DEBUG = True` fixo: página de debug em produção e `/mediafiles/` servido pelo Django | `core/settings.py:24` | `DEBUG` do ambiente, com padrão `False` e falha na subida se `SECRET_KEY` faltar |
| 2 | CRÍTICA | `GroupViewSet` com escrita liberada a qualquer usuário logado: um vendedor dá a si mesmo qualquer permissão | `api/views/usuarios.py:86-91` | `DjangoModelPermissions` + escrita só com `auth.change_group` |
| 3 | CRÍTICA | `UserSerializer` grava `is_superuser`, `is_staff`, `user_permissions` e `groups`: quem tem `add_user` cria superusuário | `api/serializers.py:629-648` | esses campos ficam só leitura; `groups` restrito ao que quem edita pode conceder |
| 4 | CRÍTICA | `RepasseViewSet` só exige login: lista e altera repasses de todas as lojas | `api/views/repasses.py:35,53-73` | permissões `financeiro.*_repasse` + `escopo_lojas` |
| 5 | ALTA | aprovar e reprovar aceitam `change_cliente`: o vendedor aprova a própria análise; várias ações de etapa não têm escopo de loja | `api/permissions.py:40-53`, `api/views/solicitacoes_etapas.py` | decisões só com `change_status_analise` + escopo de loja em todas as ações |
| 6 | ALTA | `/pagamento/<id>/` público com id sequencial expõe os pagamentos de qualquer cliente | `vendas/views/publico.py:39`, `core/middleware.py:21-35` | token aleatório (`Pagamento.token_publico`, UUID4) na URL; o id deixa de funcionar |
| 7 | ALTA | `/mediafiles/` público (RG, Serasa, fotos, documentos) | `core/middleware.py:16`, `core/urls.py:50` | view autenticada com escopo + `X-Accel-Redirect` do nginx (ou S3 privado com URL de 5 min) |
| 8 | ALTA | CORS `ALLOW_ALL_ORIGINS` + `ALLOW_CREDENTIALS` | `core/settings.py:378-379` | lista de origens no ambiente |
| 9 | ALTA | sem limite de tentativas no login, no reset e nos endpoints públicos | — | `django-axes` + throttling do DRF |
| 10 | ALTA | WebSocket sem validação de origem; aceita refresh token; não confere `is_active` | `core/asgi.py`, `notificacao/jwt_middleware.py` | `AllowedHostsOriginValidator`, exigir `token_type == "access"`, conferir `is_active` |
| 11 | MÉDIA | cookies sem `Secure`, sem HSTS e sem CSP | `core/settings.py` | `SESSION/CSRF_COOKIE_SECURE`, HSTS, CSP, `Referrer-Policy` e `Permissions-Policy` |
| 12 | MÉDIA | JWT sem rotação nem blacklist; logout só no cliente | `core/settings.py:209-215` | rotação + `token_blacklist` + endpoint de logout |
| 13 | MÉDIA | uploads da API sem validação de tipo e tamanho; `content_type` vindo do cliente | `api/serializers.py:533-571`, `api/views/fotos.py` | validador único por bytes do arquivo (como o do CRM) + limite de tamanho |
| 14 | MÉDIA | mutações por GET (aprovar análise, 11 toggles, ler todas) | `vendas/urls.py`, `notificacao/urls.py` | `require_POST` |
| 15 | MÉDIA | esquema OpenAPI e Swagger públicos; `buscar-lojas` permite descobrir usuários | `core/urls.py:45-46`, `api/views/publico.py:166` | esquema só para staff; `buscar-lojas` com limite de tentativas e resposta igual para usuário inexistente |
| 16 | MÉDIA | Redis publicado no host sem senha; container como root; script remoto no build | `docker-compose.yml`, `Dockerfile:37` | Redis só na rede interna e com senha; usuário sem privilégio; tirar o oh-my-zsh |
| 17 | BAIXA | DSN do Sentry fixo no código; e-mail por console (links de reset nos logs) | `core/settings.py:334-342,394` | variáveis de ambiente; SMTP em produção |

### 9.2 Controles da nova SPA
- **Sem tokens no navegador.** Sessão HttpOnly; nada sensível em localStorage (só preferências de interface).
- **CSP estrita** servida pelo nginx em `/painel/`:
  - `default-src 'self'`;
  - `script-src 'self'` (sem inline e sem `eval`);
  - `style-src 'self'`;
  - `img-src 'self' data: blob:` + o domínio do S3, se houver;
  - `connect-src 'self' wss://<domínio>`;
  - `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`.
- **HTML de conteúdo** (contrato do Editor.js, mensagens) passa por DOMPurify; `dangerouslySetInnerHTML` só dentro de um componente `SafeHtml` revisado.
- **Mídia e documentos** só por endpoint autenticado com escopo de loja; o acesso a RG e Serasa é auditado.
- **Auditoria:** modelo `RegistroAuditoria` (usuário, data, IP real vindo do proxy confiável, ação, tipo e id do objeto, resumo de antes e depois, motivo). Registra:
  - login, logout e falhas;
  - 2FA;
  - aprovar, reprovar e cancelar análise;
  - gerar e cancelar venda;
  - edição especial e troca;
  - quitação, parcelas e vencimentos;
  - repasses;
  - usuários, grupos e permissões;
  - acesso a documentos sensíveis.
  
  Tela de consulta só para administrador.
- **Dependências:** lockfile, `npm audit` e `pip-audit` na CI, Dependabot. Nada de CDN com `@latest`.
- **Erros:** o usuário vê mensagens amigáveis; os detalhes vão para o Sentry, sem PII.

## 10. Tempo real
- A SPA abre `wss://<domínio>/ws/notifications/` com o cookie de sessão (mesma origem) e reconecta com espera crescente.
- Cada `event` mapeia para consultas a invalidar: `proposta_criada` invalida a fila de crédito e abre o modal do analista; `crm_evento` invalida a lista e a conversa afetada.
- Com o WebSocket fora do ar, a tela da fila e o CRM fazem polling de 30 s só com a aba visível.
- O consumer passa a recusar conexão sem `acessar_backoffice`, ou sem `crm.acessar_crm` para eventos do CRM.

## 11. Estrutura do repositório `backoffice-web/`

```
backoffice-web/
├── src/
│   ├── app/            # router, providers, AppShell, guarda de rota por permissão
│   ├── design/         # tokens.css (claro/escuro), tema, fontes
│   ├── components/     # base do design system (seção 7.3) + ui/ do shadcn
│   ├── features/       # um diretório por domínio
│   │   └── credito/    # api.ts, queries.ts, schemas.ts, pages/, components/
│   │       (auth, painel, credito, vendas, financeiro, lojas, catalogo,
│   │        admin, relatorios, notificacoes, crm)
│   ├── lib/            # cliente http (CSRF, X-Loja, erro padrão), ws, format, masks, permissões
│   └── api/schema.d.ts # gerado do OpenAPI; não editar
├── e2e/                # Playwright: fluxos críticos por papel
└── .github/workflows/  # lint, typecheck, testes, verificação do contrato, build
```

## 12. Qualidade
- **Cobertura mínima de 80%.** No backend: permissões por papel e escopo de loja de cada endpoint. Na SPA: hooks e componentes.
- **E2E por papel** (analista, financeiro, admin, atendente): aprovar uma análise do começo ao fim, gerar a venda, registrar uma quitação, criar um repasse, responder uma conversa no CRM, e confirmar que o vendedor é recusado no login.
- **Testes de acessibilidade** automatizados (axe) nas telas principais. Lighthouse acima de 90 em desempenho e acessibilidade no painel.
- **Testes do backend com o venv Python 3.12** (o venv local 3.14 quebra templates em teste).

## 13. Migração e desligamento
- **Convivência:** o nginx serve `/painel/*` a partir da SPA, e o resto continua no Django. A sessão é a mesma.
- **Virada por módulo:**
  - A variável `BACKOFFICE_SPA_MODULOS` (ex.: `credito,vendas`) liga o redirecionamento das telas Django do módulo para a rota equivalente em `/painel/`.
  - Desligar a variável é o rollback.
- **Critério de "pronto" por módulo:**
  - checklist de paridade com o inventário;
  - E2E passando;
  - testes de permissão por papel;
  - uma semana de uso por 1 ou 2 usuários reais antes de ligar para todos.
- **Ordem:**
  1. Fase 0: segurança.
  2. Fundação.
  3. Crédito (maior ganho de uso).
  4. Vendas.
  5. Financeiro, lojas e repasses.
  6. Catálogo e administração.
  7. Relatórios e painel.
  8. CRM (o mais complexo em tempo real).
  9. Desligamento.
- **Desligamento:** com todos os módulos virados e duas semanas estáveis:
  - `/` passa a redirecionar para `/painel/`;
  - saem os templates, views, JS, CSS do backoffice e o tema Sneat;
  - ficam as páginas públicas e o admin.
- **Deploy:** push no `main` do `credfacil` publica em produção. As fases são commitadas no `main` local e só vão para produção quando o responsável pedir o push.

## 14. Riscos / Trade-offs
- **Escopo grande:** 72 telas e cerca de 90 endpoints novos.
  - Mitigação: módulos fatiados e virada por variável.
  - Estimativa grosseira: 4 a 5 meses para uma pessoa com apoio do Claude.
- **Correções da Fase 0 podem quebrar a SPA do vendedor** (CORS, `UserSerializer`).
  - Mitigação: conferir o que a SPA envia, testar os fluxos do vendedor antes do deploy e liberar a origem dela no CORS.
- **Duas UIs ao mesmo tempo durante meses**, com risco de divergência.
  - Mitigação: a regra fica só em `services/`; uma correção de regra vale para as duas.
- **Mesma origem exige ajuste no nginx**, cuja configuração não está versionada.
  - Mitigação: versionar a configuração do nginx no repositório nesta mudança.
- **2FA obrigatório muda a rotina dos analistas.**
  - Mitigação: ativação guiada no primeiro login, códigos de recuperação e reset de 2FA por administrador (auditado).
- **CRM em React é a parte mais arriscada** (tempo real, mídia, rascunho que não pode se perder).
  - Mitigação: vai por último, quando a base já estiver madura, e o Django fica como reserva até a paridade.

## 15. Decisões em aberto
1. **Domínio:** `/painel/` no domínio atual, ou subdomínio próprio (ex.: `backoffice.<domínio>`)? O subdomínio também é mesma origem para cookies se o Django for servido nele. A recomendação é `/painel/` no domínio atual.
2. **CRM na SPA:** confirmar que o CRM entra (recomendado: entra por último, restrito por `crm.acessar_crm`; o vendedor continua sem acesso).
3. **2FA:** confirmar quais papéis são obrigatórios. A proposta é ADMINISTRADOR, ANALISTA e quem tem permissões financeiras ou de usuários.
4. **Fase 0 já:** a recomendação é tratá-la como mudança própria e ir para produção antes de qualquer trabalho na SPA.
