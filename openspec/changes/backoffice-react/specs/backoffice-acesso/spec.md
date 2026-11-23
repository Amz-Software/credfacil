# Delta da especificação

## Purpose

Define como pessoas entram no backoffice React, como a sessão é protegida e como o servidor autoriza o acesso às lojas, aos documentos e aos eventos em tempo real.

## ADDED Requirements

### Requirement: Entrada restrita a quem tem acesso ao backoffice
A API `/api/bo/v1/` MUST autenticar somente por sessão do Django com CSRF e MUST aceitar o login apenas de usuários ativos com a permissão `accounts.acessar_backoffice`.

#### Cenário: Analista entra
- **QUANDO** um usuário ativo do grupo ANALISTA, com 2FA configurado, informar usuário, senha e código válidos
- **ENTÃO** o servidor criará uma sessão nova (`cycle_key`), gravará o cookie HttpOnly e Secure e devolverá os dados de `me`

#### Cenário: Vendedor tenta entrar
- **QUANDO** um usuário do grupo VENDEDOR, sem `accounts.acessar_backoffice`, informar credenciais corretas
- **ENTÃO** o servidor responderá 403 com o código `proibido`, não criará sessão e indicará a SPA de vendas

#### Cenário: Token JWT no backoffice
- **QUANDO** uma requisição a `/api/bo/v1/` chegar só com `Authorization: Bearer <jwt>`
- **ENTÃO** o servidor responderá 401 com o código `nao_autenticado`

### Requirement: Segundo fator para papéis sensíveis
O login MUST exigir TOTP de ADMINISTRADOR, ANALISTA e de quem tiver permissão sobre usuários, grupos, repasses ou quitação.

#### Cenário: Primeiro login sem 2FA configurado
- **QUANDO** um usuário de papel sensível entrar sem 2FA configurado
- **ENTÃO** a sessão ficará restrita à ativação do 2FA até a confirmação de um código válido, e o usuário receberá códigos de recuperação

#### Cenário: Código inválido
- **QUANDO** o código TOTP for inválido
- **ENTÃO** o login não será concluído e a falha contará para o bloqueio por tentativas

### Requirement: Bloqueio por tentativas
O servidor MUST bloquear temporariamente o login após 5 falhas em 15 minutos para a mesma combinação de usuário e IP, no backoffice, no login Django, no admin e na recuperação de senha.

#### Cenário: Sexta tentativa errada
- **QUANDO** houver 5 falhas seguidas em 15 minutos
- **ENTÃO** a próxima tentativa responderá com o código `limite_excedido` e uma mensagem com o tempo de espera, mesmo com a senha correta

### Requirement: Sessão com expiração e logout no servidor
A sessão MUST expirar após 30 minutos sem uso ou 12 horas desde o login, e o logout MUST invalidar a sessão no servidor.

#### Cenário: Inatividade
- **QUANDO** passarem 30 minutos sem requisições
- **ENTÃO** a próxima requisição responderá 401 e a SPA levará ao login, preservando a rota de retorno

#### Cenário: Encerrar outras sessões
- **QUANDO** o usuário escolher "encerrar outras sessões"
- **ENTÃO** todas as suas sessões, menos a atual, serão apagadas no servidor

### Requirement: Escopo de loja autorizado no servidor
Toda consulta e ação da API do backoffice MUST se limitar às lojas devolvidas por `escopo_lojas(request)`. A loja enviada no cabeçalho `X-Loja` MUST ser cruzada com esse escopo e nunca concede acesso por si só.

#### Cenário: Usuário comum
- **QUANDO** um usuário vinculado à loja A como usuário enviar `X-Loja: A`
- **ENTÃO** verá apenas dados da loja A

#### Cenário: Usuário comum pede outra loja
- **QUANDO** esse mesmo usuário enviar `X-Loja: B` (loja à qual não está vinculado)
- **ENTÃO** o servidor responderá 403, sem devolver dados da loja B

#### Cenário: Objeto de outra loja por id
- **QUANDO** o usuário pedir pelo id uma solicitação, venda ou pagamento da loja B
- **ENTÃO** o servidor responderá 404

#### Cenário: Gerente
- **QUANDO** um usuário que é gerente das lojas A e C enviar `X-Loja: C`
- **ENTÃO** verá os dados da loja C, e `X-Loja: todas` responderá 403 se ele não tiver permissão global

#### Cenário: Administrador
- **QUANDO** um administrador, ou usuário com a permissão global correspondente (`can_view_all_*`), enviar `X-Loja: todas`
- **ENTÃO** verá os dados de todas as lojas

### Requirement: Documentos e mídia protegidos
Arquivos de clientes, vendas e comprovantes MUST ser entregues somente por endpoint autenticado que confira permissão e escopo de loja. O acesso a RG e consultas Serasa MUST ser auditado.

#### Cenário: URL direta sem sessão
- **QUANDO** alguém sem sessão abrir o caminho de um documento de cliente
- **ENTÃO** o servidor responderá 401 ou 404, sem entregar o arquivo

### Requirement: WebSocket autenticado e com origem validada
A conexão `/ws/notifications/` MUST validar a origem, MUST aceitar apenas sessão válida ou access token (nunca refresh token) de usuário ativo e MUST entregar eventos do CRM somente a quem tem `crm.acessar_crm`.

#### Cenário: Origem de outro site
- **QUANDO** uma página de outra origem tentar abrir o WebSocket com o cookie do usuário
- **ENTÃO** a conexão será recusada

### Requirement: Trilha de auditoria
O servidor MUST registrar em `RegistroAuditoria` o usuário, a data, o IP, a ação, o objeto, um resumo da mudança e o motivo informado, para:

- autenticação e 2FA;
- decisões de análise;
- geração e cancelamento de venda;
- edição especial e troca;
- quitação, parcelas e vencimentos;
- repasses;
- usuários, grupos e permissões;
- acesso a documentos sensíveis.

#### Cenário: Reprovação
- **QUANDO** um analista reprovar uma solicitação informando o motivo
- **ENTÃO** a auditoria terá um registro com o analista, a solicitação, o status anterior e o novo, e o motivo
