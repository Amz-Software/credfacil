# Tarefas

> Cada fase é um conjunto de commits pequenos no `main` local. Push só com pedido explícito (push no `main` publica em produção).
> As estimativas são grosseiras e consideram uma pessoa com apoio do Claude.

## 0. Segurança urgente do backend (≈1 semana; pode ir para produção sozinha)

- [ ] 0.1 Ler `DEBUG` do ambiente, com padrão `False`, e falhar na subida sem `SECRET_KEY`; conferir que um erro 500 em produção mostra a página padrão e que `/mediafiles/` deixa de ser servido pelo Django.
- [ ] 0.2 Restringir a escrita em `GroupViewSet` a `auth.add_group`, `auth.change_group` e `auth.delete_group`; conferir com teste que um VENDEDOR recebe 403 ao criar e editar grupo e continua listando.
- [ ] 0.3 Deixar `is_superuser`, `is_staff` e `user_permissions` só leitura no `UserSerializer` e limitar `groups` ao que quem edita pode conceder; antes, conferir o que `front-connect-magic/src/services/usuarios.ts` envia, e conferir com teste que `add_user` não cria superusuário.
- [ ] 0.4 Exigir `financeiro.view/add/change/delete_repasse` e escopo de loja em `RepasseViewSet`; conferir com teste que um usuário sem `?loja` não lista repasses de outras lojas e que `agendados` continua funcionando para o vendedor.
- [ ] 0.5 Exigir `change_status_analise` em aprovar e reprovar e aplicar escopo de loja em todas as ações de `api/views/solicitacoes_etapas.py`; conferir com teste os cenários de usuário comum, gerente e administrador, e que id de outra loja responde 404.
- [ ] 0.6 Criar `Pagamento.token_publico` (UUID4, migração com preenchimento dos registros existentes), trocar a URL pública para `/pagamento/<token>/` e atualizar os links (consulta de pagamentos, `crm/templates/crm/parciais/painel_cliente.html`); conferir que `/pagamento/<id>/` responde 404.
- [ ] 0.7 Servir a mídia por view autenticada com escopo + `X-Accel-Redirect` (ou S3 privado) e tirar `MEDIA` da lista pública do `LoginObrigatorioMiddleware`; conferir que a SPA do vendedor ainda abre os documentos (hoje baixa sem Bearer: `front-connect-magic/src/lib/media.ts`).
- [ ] 0.8 Trocar `CORS_ALLOW_ALL_ORIGINS` por uma lista vinda do ambiente que inclua a origem da SPA do vendedor; conferir o login e uma listagem na SPA do vendedor apontando para o backend local.
- [ ] 0.9 Instalar `django-axes` (login Django, `/api/token/`, admin, reset) e throttling do DRF nos endpoints públicos (`buscar-lojas`, contrato, consulta de pagamentos); conferir o bloqueio após 5 falhas e a mensagem ao usuário.
- [ ] 0.10 WebSocket: `AllowedHostsOriginValidator` em `core/asgi.py`, recusar token que não seja access e conferir `is_active` em `notificacao/jwt_middleware.py`; conferir com teste de consumer.
- [ ] 0.11 Endurecer cookies e cabeçalhos (`*_COOKIE_SECURE`, HSTS, `Referrer-Policy`, `Permissions-Policy`); JWT com rotação + `token_blacklist` + endpoint de logout; esquema e Swagger só para staff.
- [ ] 0.12 Validador único de upload pelos bytes do arquivo, com limite de tamanho, aplicado aos campos da solicitação, da venda e do foto-upload (reaproveitar `crm/services/midias.py`).
- [ ] 0.13 `require_POST` em `aprovar_analise`, `pre_analise_rapida_aprovar`, nos 11 toggles de pagamento e em `notificacao_ler_todas`, ajustando os templates que chamam por link.
- [ ] 0.14 Infra: Redis só na rede interna e com senha; container sem root; tirar o oh-my-zsh do `Dockerfile`; DSN do Sentry e SMTP pelo ambiente.
- [ ] 0.15 Rodar a suíte completa com o venv Python 3.12 e testar à mão os fluxos do vendedor (login, nova solicitação, gerar venda, documentos).

## 1. Fundação (≈2 semanas)

- [ ] 1.1 Criar o repositório `backoffice-web/` (React 19, TS strict, Vite, TanStack Router e Query, Tailwind 4, shadcn/ui, ESLint, Prettier, Vitest, Playwright) com a estrutura da `design.md`, seção 11.
- [ ] 1.2 Implementar os tokens da paleta (`design.md`, seção 7.1) em `src/design/tokens.css`, claro e escuro, com teste automatizado de contraste dos pares de texto e fundo; converter a logo IPIX para SVG.
- [ ] 1.3 Componentes base (`design.md`, seção 7.3) com histórias de uso e testes, incluindo `DataTable` com filtros na URL e `ConfirmDialog` com motivo.
- [ ] 1.4 Backend: app `backoffice_api/` com `SessionAuthentication` + CSRF, exception handler do contrato de erro, paginação padrão, `escopo_lojas(request)` com o cabeçalho `X-Loja` e a permissão `accounts.acessar_backoffice` (migração de dados concedendo a permissão a ANALISTA e ADMINISTRADOR).
- [ ] 1.5 Endpoints de autenticação (`csrf`, `login`, `otp`, `logout`, `me`, `sessoes`) com `django-otp` (TOTP + códigos de recuperação), expiração por inatividade e `cycle_key`; testes: vendedor recusado, 2FA obrigatório por papel, bloqueio por tentativas, logout que invalida a sessão.
- [ ] 1.6 Modelo `RegistroAuditoria` + serviço `auditar(...)`, chamado pelo login e pelo logout; IP real vindo do proxy confiável.
- [ ] 1.7 SPA: cliente http (CSRF, `X-Loja`, erro padrão, 401 levando ao login, 403 com tela própria), `AppShell` com menu por permissão, seletor de loja, busca global (Ctrl+K) com navegação, tema e menu do usuário; telas de login, 2FA, perfil, senha e sessões.
- [ ] 1.8 WebSocket na SPA (cookie, reconexão, mapa de `event` para invalidação) e centro de notificações (lista, marcar lida, todas) com os endpoints novos.
- [ ] 1.9 Geração de tipos do OpenAPI na CI com verificação de divergência; workflow da SPA (lint, typecheck, testes, build, `npm audit`).
- [ ] 1.10 Configuração do nginx versionada: `/painel/` servindo o `dist/` (cache longo nos assets com hash, `index.html` sem cache), CSP estrita e o resto encaminhado ao Django; variável `BACKOFFICE_SPA_MODULOS` e o redirecionamento por módulo no Django.

## 2. Crédito: fila de análise e pré-análise (≈3 semanas)

- [ ] 2.1 API: lista da fila (filtros da `vendas/filtros.py`, KPIs, contadores), detalhe com linha do tempo (simple_history + observações), observações, aprovar, reprovar e cancelar com motivo auditado, ações do analista (status do app, instalar, confirmar app, iCloud, informar IMEI), log de consulta Serasa; tudo por `vendas/services/analise.py` e com escopo de loja.
- [ ] 2.2 API: edição da solicitação pelo analista, reaproveitando os forms e o cadastro atual (`api/views/solicitacoes_cadastro.py`); conferir entrada, envio, persistência, leitura, edição e recarga dos dados do cliente, dos comprovantes e do parcelamento por marca.
- [ ] 2.3 API: gerar venda a partir da análise por `vendas/services/venda.py` (juros e desconto do `Parcelamento` da marca e da quantidade de parcelas); conferir que a venda gerada é igual à da tela Django para o mesmo caso, iPhone e não iPhone.
- [ ] 2.4 SPA: fila com cronômetro, tempo real, atalhos de teclado e painel lateral; detalhe em abas (Análise, Dados, Comprovantes, Histórico) com visualizador de documentos autenticado e modal de "nova proposta" para o analista.
- [ ] 2.5 SPA e API: pré-análise rápida (lista, detalhe, aprovar, reprovar com motivo, upload e remoção do Serasa, PDF no servidor).
- [ ] 2.6 E2E do analista do começo ao fim + testes de permissão por papel; checklist de paridade com o inventário; beta com 1 ou 2 analistas e virada de `credito` em `BACKOFFICE_SPA_MODULOS`.

## 3. Vendas (≈2 semanas)

- [ ] 3.1 API: lista (filtros atuais: canceladas, trocadas, cliente, número), detalhe, edição, edição especial (`can_edit_imei_valores_venda`), troca de produto, cancelar com motivo, documentos (com o validador de upload) e produtos vendidos; conferir entrada, envio, persistência, leitura, edição e recarga de itens e pagamentos, nos fluxos manual e de análise.
- [ ] 3.2 PDFs no servidor (WeasyPrint) para nota, carnê com QR PIX e contrato (Editor.js convertido no servidor), no lugar do html2pdf e do `window.print`.
- [ ] 3.3 Autorização de desconto pelo gerente (`/autorizacao/`) como endpoint do backoffice com limite de tentativas e auditoria.
- [ ] 3.4 SPA: lista, detalhe, gaveta de edição, edição especial, troca e documentos; E2E; paridade; virada de `vendas`.

## 4. Financeiro, lojas e repasses (≈3 semanas)

- [ ] 4.1 API de contas a receber: lista com filtros e situações, detalhe, situações (substituindo os 11 toggles, com histórico), desconto, parcelas (editar, adicionar até 4, vencimento com `change_vencimento_parcela`), comprovantes (upload, download autenticado, exclusão), quitação (`can_confirm_quitacao`) e contatos; conferir entrada, envio, persistência, leitura, edição e recarga de parcelas e pagamentos.
- [ ] 4.2 BO: prévia + PDF no servidor (exige parcela vencida), com as referências guardadas no servidor em vez da sessão.
- [ ] 4.3 API de lojas (lista, detalhe, formulário com logo, QR code e contrato do Editor.js, replicar QR), calendário de repasses dos dias 6, 16 e 26 e CRUD de repasses com escopo; números autenticadores.
- [ ] 4.4 SPA: contas a receber (lista, detalhe com gaveta de parcela, situações, comprovantes, quitação), tela de Repasses, lojas e números autenticadores; E2E financeiro; paridade; virada de `financeiro` e `lojas`.

## 5. Catálogo e administração (≈2 semanas)

- [ ] 5.1 SPA e API: produtos (ativar, desativar, PDF), marcas (com lojas permitidas), tipos e parcelamentos.
- [ ] 5.2 SPA e API: usuários (sem poder conceder superusuário ou grupo acima do próprio), grupos com matriz de permissões por domínio, reset de 2FA por administrador (auditado) e consulta da auditoria.
- [ ] 5.3 E2E do administrador; paridade; virada de `catalogo` e `admin`.

## 6. Relatórios e painel (≈2 semanas)

- [ ] 6.1 Central de relatórios: vendas, solicitações, contas a receber, situações e parcelas, com filtros padronizados e geração no servidor (PDF via WeasyPrint, Excel via openpyxl); permissões atuais mantidas (incluindo `can_genarate_report_payments`, com a grafia do código).
- [ ] 6.2 Painel por papel e gráficos (`GraficoTemplateView`, `DashboardReportPDFView`, `dashboard-clientes-quitados` sem mudar a regra), seguindo a skill `dataviz`.
- [ ] 6.3 Paridade; virada de `relatorios` e `painel`.

## 7. CRM WhatsApp (≈3–4 semanas)

- [ ] 7.1 API JSON do CRM sobre os serviços existentes: conversas (filtros, contadores, cursor de mensagens), ações (assumir, puxar, atribuir, devolver, situação, etiquetas, apelido, vincular cliente, abertura), envio com mídia (25 MB, tipo pelos bytes), reações, digitando, notas, lembretes, programadas, resumo de pagamentos e prévia de resposta; `crm.acessar_crm` e `crm.gerenciar_crm` em cada endpoint.
- [ ] 7.2 Mídia autenticada (Range, miniatura, `LogAcessoMidia`) e eventos `crm_evento` só para quem tem `crm.acessar_crm`.
- [ ] 7.3 SPA: caixa em 3 colunas com listas virtualizadas, compositor que preserva o rascunho em atualizações em tempo real, botão "novas mensagens", painel do cliente e modais; configuração (aberturas com sincronização da Meta, etiquetas, respostas, simulador).
- [ ] 7.4 E2E do atendente (com o simulador, sem credenciais da Meta); paridade com o inventário (seção 2.11); virada de `crm`.

## 8. Desligamento (≈1 semana)

- [ ] 8.1 Com todos os módulos virados e duas semanas estáveis, `/` passa a redirecionar para `/painel/`; remover templates, views web, `static/js`, `static/css` do backoffice e o tema Sneat, mantendo as páginas públicas, o admin e os templates de PDF usados pela API.
- [ ] 8.2 Remover `django_select2`, os endpoints AJAX das telas antigas e as rotas mortas; atualizar o `CLAUDE.md` e o `docs/`; `manage.py check` e a suíte completa sem erros.
- [ ] 8.3 Arquivar esta mudança no OpenSpec, registrando os módulos, contratos e comportamentos efetivamente alterados.
