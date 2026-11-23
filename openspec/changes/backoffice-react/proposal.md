# Proposta: Novo backoffice em React

## Por quê

O backoffice hoje é server-rendered em Django: tema Sneat com Bootstrap e jQuery, três versões de Select2, html2pdf e Editor.js vindos de CDN, e scripts por tela. São 72 telas autenticadas, 71 ações POST, 15 documentos e 18 endpoints AJAX. O resultado:

- **Usabilidade irregular.** Cada tela filtra, pagina e confirma ações do seu jeito. Não há busca global nem seletor de loja. A fila do analista é atualizada por polling a cada 15 s. Rotas que alteram dados aceitam GET.
- **Visual desalinhado da marca.** O amarelo do tema (`#FDC600`) e o mostarda da SPA do vendedor (`hsl(42 80% 46%)`) diferem do amarelo da logo (`#FFDD21`).
- **Segurança com falhas sérias, abertas hoje em produção** (detalhadas em `design.md`, seção 9):
  - qualquer usuário logado altera grupos e permissões pela API;
  - quem tem `add_user` cria superusuários;
  - repasses de todas as lojas são legíveis por qualquer usuário logado;
  - quem tem `change_cliente` aprova a própria análise;
  - `DEBUG = True` está fixo no código;
  - `/mediafiles/` (RG, Serasa, fotos) é público;
  - `/pagamento/<id>/` é público com id sequencial.

O objetivo é um backoffice **profissional, organizado, bonito e seguro**: uma SPA React nova e separada da SPA do vendedor, com a paleta da logo, padrões de interface únicos e autorização sempre no servidor.

## O que muda

- **Fase 0, segurança urgente do backend.** Corrigir as falhas críticas e altas da API e da infraestrutura atuais. É independente da SPA e deve ir para produção primeiro, porque protege também a SPA do vendedor.
- **Nova SPA `backoffice-web/`** (repositório irmão de `credfacil/` e `front-connect-magic/`), servida na **mesma origem** do Django em `/painel/`. Público: analista, administrador, financeiro e atendente do CRM. Vendedores continuam só na SPA atual.
- **Nova API do backoffice `/api/bo/v1/`.** Autenticação só por sessão (cookie HttpOnly) com CSRF, contrato padronizado de erro e paginação, escopo de loja resolvido por uma função central e regra de negócio reaproveitada de `vendas/services/`. A API JWT do vendedor (`/api/`) continua existindo e não ganha endpoints do backoffice.
- **Acesso endurecido.** Permissão `acessar_backoffice`, 2FA (TOTP) obrigatório para papéis sensíveis, bloqueio por tentativas, sessão com expiração por inatividade, logout no servidor e trilha de auditoria.
- **Design system da marca.** Amarelo IPIX `#FFDD21` + tinta (preto da logo) + branco, com escalas que passam no contraste AA, modo claro e escuro e componentes únicos (tabela de dados, filtros, cabeçalho, status, linha do tempo).
- **Arquitetura de informação refeita.** Menu por domínio, busca global (Ctrl+K), seletor de loja, fila de análise em tempo real, central de relatórios e impressos gerados no servidor (PDF).
- **Migração gradual (strangler).** Módulo a módulo; as telas Django ficam no ar até cada módulo novo atingir paridade. A sessão compartilhada permite navegar entre tela velha e nova sem novo login.
- **Desligamento.** No fim, as telas Django do backoffice saem. As páginas públicas do cliente (consulta de pagamentos, privacidade, foto pelo celular, reset de senha) ficam no Django, com as correções de segurança da Fase 0.

## Capacidades

### Novas capacidades
- `backoffice-acesso`: autenticação por sessão, 2FA, bloqueio por tentativas, permissão de entrada, escopo de loja no servidor, WebSocket autenticado, auditoria e mídia protegida.
- `backoffice-api`: contrato da API `/api/bo/v1/` (versão, erro, paginação, ações, esquema OpenAPI) e sua convivência com a API do vendedor.
- `backoffice-interface`: SPA do backoffice, com design system da marca, navegação, padrões de lista, detalhe e formulário, tempo real, acessibilidade e migração por módulo.

### Capacidades modificadas
- Nenhuma especificação existente é alterada (a única em `openspec/specs/` é `dashboard-clientes-quitados`, que será portada sem mudar a regra).

## Impacto

- **Interface web:** nova SPA em `backoffice-web/`. As telas Django de `vendas`, `financeiro`, `produtos`, `accounts`, `notificacao` e `crm/web` são substituídas por fases e removidas na Fase 8. As páginas públicas continuam no Django.
- **API REST:**
  - Novo namespace `/api/bo/v1/` (sessão + CSRF).
  - Fase 0 muda contratos da API atual. Efeitos na SPA do vendedor:
    - `aprovar`/`reprovar` deixam de aceitar `change_cliente`. O vendedor não usa essas ações.
    - CRUD de `/api/repasses/` passa a exigir permissão e escopo de loja. O vendedor usa só `agendados`, que já tem escopo.
    - `/api/groups/` fica restrito para escrita. O vendedor só lista.
    - `UserSerializer` deixa `is_superuser`, `is_staff` e `user_permissions` só leitura e restringe `groups`. **Conferir** o que `front-connect-magic/src/services/usuarios.ts` envia na criação e edição.
    - CORS deixa de liberar todas as origens. A origem da SPA do vendedor precisa entrar na lista.
- **WebSocket:** `/ws/notifications/` ganha validação de origem, recusa refresh token e confere `is_active`. A SPA do backoffice conecta por cookie de sessão (mesma origem), e os eventos `event` e `crm_evento` passam a invalidar consultas na SPA.
- **Sessões e permissões:** nova permissão `accounts.acessar_backoffice`; expiração por inatividade; 2FA para ADMINISTRADOR, ANALISTA e quem gerencia usuários, permissões ou financeiro.
- **Banco de dados:** tabelas do `django-otp` e do `django-axes`, modelo `RegistroAuditoria` e um token público aleatório no `Pagamento` para substituir o id sequencial na URL pública. Nenhuma mudança nos modelos de venda, análise ou parcela.
- **Vendas:** os dois fluxos (manual e originado por análise de crédito) mantêm a regra atual. A geração da venda continua em `vendas/services/venda.py`, com juros e desconto do `Parcelamento` por marca e quantidade de parcelas.
- **Infra/deploy:**
  - nginx serve `backoffice-web/dist` em `/painel/` com CSP;
  - novo workflow de CI para a SPA;
  - Redis com senha e sem porta publicada;
  - container sem root.
- **Dependências novas no backend:** `django-otp`, `django-axes`, `django-csp` (ou cabeçalhos no nginx). Na SPA: veja `design.md`, seção 3.
