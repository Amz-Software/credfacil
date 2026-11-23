# Delta da especificação

## Purpose

Define o contrato da API do backoffice (`/api/bo/v1/`) e as mudanças de contrato da API atual (`/api/`) feitas na Fase 0, com os efeitos sobre a SPA do vendedor.

## ADDED Requirements

### Requirement: Contrato de erro único
Toda resposta de erro da API do backoffice MUST seguir `{"erro": {"codigo", "mensagem", "campos"}}`. `codigo` é um destes valores: `validacao`, `nao_autenticado`, `proibido`, `nao_encontrado`, `conflito`, `regra_de_negocio`, `limite_excedido`.

#### Cenário: Campo inválido
- **QUANDO** um formulário for enviado com CPF inválido
- **ENTÃO** a resposta será 400 com `codigo = "validacao"` e `campos.cpf` com a mensagem

#### Cenário: Regra de negócio
- **QUANDO** o serviço levantar `ErroDeNegocio` (por exemplo, marca sem `Parcelamento` para a quantidade de parcelas escolhida)
- **ENTÃO** a resposta será 422 com `codigo = "regra_de_negocio"` e a mensagem pronta do serviço

#### Cenário: Id inexistente
- **QUANDO** um recurso for pedido por um id que não existe ou que está fora do escopo
- **ENTÃO** a resposta será 404 com `codigo = "nao_encontrado"`, nunca 500

### Requirement: Paginação padrão
Listas MUST responder `{"count", "page", "page_size", "total_pages", "results"}`. `page_size` é aceito até 100, com padrão 25, e a ordenação vem de `?ordenar=`.

#### Cenário: Página maior que o limite
- **QUANDO** a SPA pedir `page_size=500`
- **ENTÃO** a resposta usará 100 itens por página e informará `page_size = 100`

### Requirement: Mutações somente por POST, PUT, PATCH ou DELETE
Nenhuma ação que altere dados MUST aceitar GET, na API do backoffice ou nas telas Django que continuarem no ar.

#### Cenário: Aprovar por link
- **QUANDO** alguém abrir por GET a rota de aprovar uma análise
- **ENTÃO** o servidor responderá 405 e nada será alterado

### Requirement: Regra de negócio única
Os endpoints do backoffice MUST delegar a regra aos serviços existentes (`vendas/services/*` e serviços do CRM), para que a tela Django e a SPA produzam o mesmo resultado durante a convivência.

#### Cenário: Gerar venda pela SPA
- **QUANDO** o analista gerar a venda de uma análise aprovada pela SPA
- **ENTÃO** a venda, os pagamentos ENTRADA e IPX e as parcelas serão iguais aos gerados pela tela Django para os mesmos dados
- **E** os juros e o desconto virão do `Parcelamento` da marca do produto e da quantidade de parcelas
- **E** a entrada será `entrada_informada` ou `produto.entrada_cliente`

### Requirement: Esquema OpenAPI restrito e usado para tipar a SPA
O esquema da API MUST ser servido apenas a usuários staff autenticados, e a CI da SPA MUST falhar quando os tipos gerados divergirem do esquema.

#### Cenário: Acesso anônimo ao esquema
- **QUANDO** alguém sem sessão staff abrir `/api/schema/` ou `/api/docs/`
- **ENTÃO** o servidor responderá 401 ou 403

## MODIFIED Requirements

### Requirement: Permissões da API atual (Fase 0)
A API `/api/` MUST exigir permissões específicas para operações administrativas. Efeitos para a SPA do vendedor:

| Mudança | Efeito na SPA do vendedor |
|---|---|
| Escrita em `/api/groups/` passa a exigir `auth.add/change/delete_group` | Só lista grupos; não muda |
| `UserSerializer` não grava mais `is_superuser`, `is_staff` nem `user_permissions`, e só aceita os `groups` que quem edita pode conceder | Conferir os campos enviados na criação e edição de usuário antes do deploy |
| `/api/repasses/` (CRUD) passa a exigir `financeiro.*_repasse` e escopo de loja | Usa só `agendados`, que já confere a loja; não muda |
| `aprovar`/`reprovar` passam a exigir `change_status_analise` | Não usa essas ações; não muda |
| Ações de etapa da solicitação passam a conferir escopo de loja | Ações do próprio vendedor nas lojas dele continuam funcionando |
| CORS passa a aceitar só as origens configuradas | A origem da SPA do vendedor precisa estar configurada |
| `/mediafiles/` deixa de ser público | A SPA precisa abrir documentos por endpoint autenticado |

#### Cenário: Vendedor tenta aprovar
- **QUANDO** um usuário com `change_cliente`, mas sem `change_status_analise`, chamar `POST /api/solicitacoes/{id}/aprovar/`
- **ENTÃO** a resposta será 403 e o status da análise não mudará

#### Cenário: Criar usuário com superusuário
- **QUANDO** um usuário com `add_user` enviar `is_superuser: true` na criação
- **ENTÃO** o usuário criado não será superusuário

#### Cenário: Repasses sem loja
- **QUANDO** um usuário sem permissão global listar `/api/repasses/` sem `?loja`
- **ENTÃO** receberá apenas repasses das lojas do seu escopo, ou 403 se não tiver `financeiro.view_repasse`

### Requirement: Página pública de pagamento por token
A página pública de pagamento MUST ser acessada por um token aleatório (`Pagamento.token_publico`), e não pelo id sequencial.

#### Cenário: Tentativa por id
- **QUANDO** alguém abrir `/pagamento/<id numérico>/`
- **ENTÃO** a resposta será 404

#### Cenário: Link da consulta de pagamentos
- **QUANDO** o cliente consultar seus pagamentos com CPF e data de nascimento corretos
- **ENTÃO** os links levarão a `/pagamento/<token>/` e mostrarão os dados como hoje
