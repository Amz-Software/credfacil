# CredFacil API

- Health check: `GET /api/health/`
- OpenAPI (JSON): `GET /api/schema/`
- Swagger UI: `GET /api/docs/`

## Autenticacao

A API aceita dois modos:
- JWT Bearer token
- Session authentication (para uso via navegador/Swagger)

### Login via JWT

Para obter os tokens de acesso, envie uma requisição POST:

```
POST /api/token/
Content-Type: application/json

{
  "username": "seu_usuario",
  "password": "sua_senha"
}
```

Resposta:

```json
{
  "access": "<access_token>",
  "refresh": "<refresh_token>",
  "user": {
    "id": 1,
    "username": "seu_usuario",
    "first_name": "Nome",
    "last_name": "Sobrenome",
    "email": "email@exemplo.com",
    "is_active": true,
    
    // Flags de administrador
    "is_admin": false,
    "is_superuser": false,
    "is_staff": false,
    
    // Grupos do usuário
    "grupos_nomes": ["VENDEDOR"],
    "groups": [
      {
        "id": 1,
        "name": "VENDEDOR",
        "permissions": [1, 2, 3]
      }
    ],
    
    // Permissões diretas
    "user_permissions": [],
    
    // TODAS as permissões efetivas (usuário + grupos)
    "todas_permissoes": [
      "vendas.add_cliente",
      "vendas.add_venda",
      "vendas.view_cliente",
      "vendas.view_venda",
      "financeiro.view_repasse",
      // ... todas as outras permissões
    ],
    
    // Lojas
    "loja": 1,
    "loja_principal": {
      "id": 1,
      "nome": "Loja Principal",
      "cnpj": "12345678000190"
    },
    "lojas_acesso": [
      {
        "id": 1,
        "nome": "Loja A",
        "cnpj": "12345678000190"
      },
      {
        "id": 2,
        "nome": "Loja B",
        "cnpj": "98765432000110"
      }
    ],
    "lojas_gerenciadas": [
      {
        "id": 1,
        "nome": "Loja A",
        "cnpj": "12345678000190"
      }
    ],
    
    // Permissões específicas (flags booleanas para facilitar)
    "acessos": {
      // Admin
      "is_admin": false,
      "is_superuser": false,
      
      // Lojas
      "pode_ver_todas_lojas": false,
      "pode_criar_loja": false,
      "pode_editar_loja": false,
      "pode_deletar_loja": false,
      "pode_ver_loja": true,
      
      // Repasses
      "pode_criar_repasse": false,
      "pode_ver_repasse": true,
      "pode_editar_repasse": false,
      "pode_deletar_repasse": false,
      
      // Produtos
      "pode_criar_produto": false,
      "pode_editar_produto": false,
      "pode_deletar_produto": false,
      "pode_ver_produto": true,
      
      // Solicitações/Clientes
      "pode_criar_solicitacao": true,
      "pode_criar_cliente": true,
      "pode_editar_cliente": true,
      "pode_ver_cliente": true,
      
      // Análise de Crédito
      "pode_criar_analise": true,
      "pode_editar_analise": true,
      "pode_ver_todas_analises": false,
      "pode_mudar_status_analise": false,
      
      // Vendas
      "pode_criar_venda": true,
      "pode_editar_venda": true,
      "pode_deletar_venda": false,
      "pode_ver_venda": true,
      "pode_ver_todas_vendas": false,
      "pode_editar_venda_finalizada": false,
      
      // Usuários
      "pode_criar_usuario": false,
      "pode_editar_usuario": false,
      "pode_deletar_usuario": false,
      "pode_ver_usuario": false
    }
  }
}
```

### Informações retornadas no login

O response do login inclui informações completas sobre o usuário:

#### Administração
- `user.is_admin`: True se o usuário é superuser ou staff
- `user.is_superuser`: True se o usuário é superusuário (acesso total)
- `user.is_staff`: True se o usuário pode acessar o Django Admin

#### Grupos e Permissões
- `user.grupos_nomes`: Array com nomes dos grupos (ex: `["VENDEDOR", "GERENTE"]`)
- `user.groups`: Array com objetos completos dos grupos
- `user.user_permissions`: Permissões diretas do usuário
- `user.todas_permissoes`: **Array com TODAS as permissões efetivas** (incluindo as dos grupos)
  - Formato: `["app.codename", "vendas.add_venda", ...]`
  - Use isso para verificar se o usuário tem uma permissão específica

#### Lojas
- `loja_selecionada`: Loja atualmente selecionada na sessão (se fornecido `loja_id` no login)
- `user.loja_principal`: Loja principal do usuário (FK User.loja)  
- `user.lojas_acesso`: Lojas onde o usuário está cadastrado como usuário
- `user.lojas_gerenciadas`: Lojas onde o usuário é gerente

#### Acessos Específicos
- `user.acessos`: Objeto com **flags booleanas** para facilitar verificação de permissões
  - Permissões para: admin, lojas, repasses, produtos, clientes, análises, vendas, usuários
  - Ex: `acessos.pode_criar_venda`, `acessos.pode_ver_todas_analises`, `acessos.is_admin`

**Importante**: 
- Use `user.is_admin` ou `user.is_superuser` para verificar se é administrador
- Use `user.todas_permissoes` para verificar permissões específicas
- Use `user.acessos` para facilitar verificações no frontend (já vem como boolean)

### Refresh Token

Para renovar o access token:

```
POST /api/token/refresh/
Content-Type: application/json

{
  "refresh": "<refresh_token>"
}
```

### Uso do Token

Exemplo de uso no header:

```
Authorization: Bearer <access_token>
```

## Usuarios

Rotas baseadas em `UserViewSet`.

### `GET /api/users/me/`

Retorna informações completas do usuário autenticado, incluindo lojas acessíveis e permissões.

Resposta: mesmo formato do objeto `user` retornado no login.

### `GET /api/users/`

Lista usuários (com paginação). Suporta query params:

- `search` (opcional): busca por username, first_name, last_name ou email
- `raw=1` ou `all=1` (opcional): retorna lista sem paginação

### `GET /api/users/{id}/`

Retorna detalhes de um usuário específico.

### `POST /api/users/`

Cria novo usuário. Campos obrigatórios: `username`, `email`, `password`.

### `PUT/PATCH /api/users/{id}/`

Atualiza usuário.



## Resposta de erro (padrao)

A API normalmente retorna:

```json
{
  "detail": "Mensagem de erro"
}
```

Ou, quando ha validacao de formularios compostos:

```json
{
  "detail": "Erros de validacao.",
  "errors": {
    "cliente": {"campo": ["erro"]},
    "contato_adicional": {"campo": ["erro"]}
  }
}
```

## Lojas

Rotas baseadas em `LojaViewSet`.

### Permissoes de acesso em lojas

- `list` e `retrieve`: exige `vendas.view_loja`
- `create`: exige `vendas.add_loja`
- `update`/`partial_update` e `replicar-qrcode`: exige `vendas.change_loja`
- `destroy`: exige `vendas.delete_loja`
- `repasses` (`GET`/`POST`): exige respectivamente `financeiro.view_repasse` e `financeiro.add_repasse`

Regra de escopo (quem pode entrar/ver cada loja):

- Se o usuario **nao** tem `vendas.can_view_all_stores`, a API restringe a visualizacao para:
  - `loja_id` da sessao (quando existir), ou
  - lojas associadas em `user.lojas`, ou
  - `user.loja` (fallback)
- Se nao houver vinculo, a listagem retorna vazia.

### `GET /api/lojas/`

Lista lojas visiveis para o usuario.

Query params:

- `search` (opcional): filtra por `nome` (`icontains`)
- `filter` (opcional): `pendente` ou `sem_pendente`

### `POST /api/lojas/`

Cria loja.

Payload: campos do modelo `Loja`.

### `GET /api/lojas/{id}/`

Retorna detalhe enriquecido da loja, com repasses, vendas e KPIs.

Query params:

- `data_inicio` (opcional, `YYYY-MM-DD`)
- `data_fim` (opcional, `YYYY-MM-DD`)
- `repasse_page` (opcional)
- `venda_page` (opcional)

Resposta inclui:

- `loja` (inclui tambem `usuarios_detalhes` e `gerentes_detalhes`)
- `contrato`
- `repasses` (paginado; vazio quando o usuario nao possui `financeiro.view_repasse`)
- `vendas` (paginado)
- `repasse_status_list` (vazio sem permissao de visualizar repasse)
- `repasse_atrasados`
- `kpi_valor_repasse`
- `kpi`
- `acessos` (flags de permissao: `pode_editar_loja`, `pode_criar_repasse`, `pode_ver_repasse`, `can_view_all_stores`)

### `PUT/PATCH /api/lojas/{id}/`

Atualiza loja.

### `GET /api/lojas/{id}/repasses/`

Lista repasses da loja (paginado).

- Exige permissao `financeiro.view_repasse`.
- Query param: `repasse_page` (opcional).

### `POST /api/lojas/{id}/repasses/`

Cria repasse para a loja.

- Exige permissao `financeiro.add_repasse`.
- Payload:
  - `valor`
  - `data`
  - `status` (`pendente`, `pago`, `cancelado`)
  - `observacao` (opcional)

### `POST /api/lojas/{id}/replicar-qrcode/`

Replica `qr_code_aplicativo` e `codigo_aplicativo` da loja atual para as demais.

Payload: vazio.

## Solicitacoes de credito

Rotas baseadas em `SolicitacaoCreditoViewSet`.

### `GET /api/solicitacoes/`

Lista solicitacoes (clientes com analise), com KPIs no retorno paginado.

Query params:

- `search` (opcional): nome do cliente
- `status` (opcional): status da analise (`EA`, `A`, `R`, `C`)
- `status_app` (opcional): status do app (`P`, `C`, `I`)
- `analise_online` (opcional): `1` ou `0`
- `loja` (opcional): id da loja
- `data_inicio` (opcional): data inicial (`YYYY-MM-DD`)
- `data_fim` (opcional): data final (`YYYY-MM-DD`)
- `vendas_nao_finalizadas` (opcional): qualquer valor para filtrar `venda is null`

Resposta paginada inclui:

- `count`, `num_pages`, `page`, `results`
- `kpis`
- `status_choices`
- `status_app_choices`

### `GET /api/solicitacoes/{cliente_id}/`

Detalhe completo da solicitacao do cliente.

### `POST /api/solicitacoes/`

Cria solicitacao completa (cliente + contato + informacao pessoal + comprovantes + analise).

Content-Type recomendado: `multipart/form-data` (por causa dos arquivos).

Campos obrigatorios do payload:

- Cliente:
- `nome`, `telefone`, `cpf`, `nascimento`, `rg`, `cep`, `endereco`, `bairro`, `cidade`, `profissao`, `quantidade_dependentes`, `recebe_auxilio`, `total_renda`
- Contato adicional:
- `nome_adicional`, `contato`, `endereco_adicional`
- Informacao pessoal:
- `nome_pessoal`, `contato_pessoal`, `endereco_pessoal`
- Comprovantes:
- `documento_identificacao_frente`, `documento_identificacao_verso`, `comprovante_residencia`, `foto_cliente`
- Analise de credito:
- `produto`, `data_pagamento`, `numero_parcelas`

Campos opcionais:

- `obteve_contato`, `obteve_contato_pessoal`
- `consulta_serasa`, `restricao`
- `analise_online`
- `email_icloud`, `senha_icloud`

Exemplo (multipart simplificado):

```json
{
  "nome": "Fulano",
  "telefone": "11999999999",
  "cpf": "12345678900",
  "nascimento": "1990-01-01",
  "rg": "1234567",
  "cep": "01001000",
  "endereco": "Rua A",
  "bairro": "Centro",
  "cidade": "Sao Paulo",
  "profissao": "Vendedor",
  "quantidade_dependentes": 0,
  "recebe_auxilio": false,
  "total_renda": "3500.00",
  "nome_adicional": "Beltrano",
  "contato": "11988887777",
  "endereco_adicional": "Rua B",
  "nome_pessoal": "Ciclano",
  "contato_pessoal": "11977776666",
  "endereco_pessoal": "Rua C",
  "produto": 1,
  "data_pagamento": "10",
  "numero_parcelas": "6",
  "analise_online": false
}
```

### `PUT/PATCH /api/solicitacoes/{cliente_id}/`

Atualiza solicitacao completa, com mesmas regras do fluxo web.

Payload: mesmo formato de criacao.

### `POST /api/solicitacoes/{cliente_id}/imei-telefone/`

Atualiza telefone do cliente + IMEI da analise.

Campos esperados:

- `telefone`
- `produto`
- `data_pagamento`
- `numero_parcelas`
- `imei`

### `POST /api/solicitacoes/{cliente_id}/status-app/`

Atualiza `status_aplicativo`.

Campos:

- `status_app`: `P`, `C` ou `I`

### `POST /api/solicitacoes/{cliente_id}/instalar-app/`

Marca status de app como confirmacao pendente (`C`).

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/confirmar-app/`

Marca status como `C` e dispara notificacoes para analistas/admins.

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/configurar-icloud/`

Vendedor confirma que configurou iCloud no iPhone.

Validacoes principais:

- exige `email_icloud` e `senha_icloud` na analise
- marca `icloud_configurado_vendedor=True`
- envia notificacao para `ANALISTA` e `ADMINISTRADOR`

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/analista-confirm-icloud/`

Analista confirma configuracao do iCloud.

Validacoes principais:

- usuario deve estar no grupo `ANALISTA`
- exige `icloud_configurado_vendedor=True`
- marca `icloud_confirmado_analista=True`
- envia notificacao para `VENDEDOR`, `ADMINISTRADOR` e `ANALISTA`

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/analista-confirmar-instalacao/`

Analista confirma instalacao do app (fluxo Android).

Validacoes principais:

- usuario deve estar no grupo `ANALISTA`
- exige IMEI informado
- exige `status_aplicativo='C'`
- altera para `status_aplicativo='I'`
- envia notificacao para `VENDEDOR`, `ADMINISTRADOR` e `ANALISTA`

Payload: vazio.

### `POST /api/solicitacoes/analises/{analise_id}/informar-imei/`

Analista informa IMEI diretamente na analise.

Validacoes principais:

- usuario deve estar no grupo `ANALISTA`
- iPhone: exige `icloud_confirmado_analista=True`
- Android: exige `status_aplicativo='C'`
- se IMEI existir no estoque da loja/sessao: associa
- se nao existir: cria `EstoqueImei` e associa
- Android: apos informar IMEI, altera para `status_aplicativo='I'`

Payload:

```json
{
  "imei_informado": "123456789012345"
}
```

### `POST /api/solicitacoes/{cliente_id}/aprovar/`

Aprova analise.

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/reprovar/`

Reprova analise.

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/cancelar/`

Cancela analise.

Payload: vazio.

### `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

Gera venda a partir da solicitacao, seguindo as mesmas regras do fluxo existente:

- validacao de parcelas pagas por CPF
- analise aprovada
- IMEI informado
- validacoes iPhone/iCloud
- caixa aberto
- cria venda, produto_venda, pagamentos e parcelas

Permissao minima:

- `vendas.add_venda`

Payload: vazio.

### Mapeamento do dropdown da tela de clientes (fluxo de solicitacao)

Itens do dropdown enviado no front correspondem aos seguintes endpoints da API:

- `Configurar iCloud (Vendedor)` → `POST /api/solicitacoes/{cliente_id}/configurar-icloud/`
- `Confirmar iCloud (Analista)` → `POST /api/solicitacoes/{cliente_id}/analista-confirm-icloud/`
- `Informar IMEI (Analista)` → `POST /api/solicitacoes/analises/{analise_id}/informar-imei/`
- `Confirmar Leitura QR (Vendedor)` → `POST /api/solicitacoes/{cliente_id}/confirmar-app/`
- `Confirmar Instalacao (Analista)` → `POST /api/solicitacoes/{cliente_id}/analista-confirmar-instalacao/`
- `Gerar Venda (Vendedor)` → `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

## Produtos

Rotas baseadas em `ProdutoViewSet`.

### `GET /api/produtos/`

Lista produtos.

Query params:

- `search` (opcional): nome do produto

Observacao:

- usuarios com `produtos.view_all_produtos` veem ativos e inativos
- demais veem apenas `ativo=True`

### `POST /api/produtos/`

Cria produto. Exige permissão `produtos.add_produto`.

Payload: campos do modelo `Produto`.

Campos principais:

- `nome` (obrigatório): nome do produto;
- `fabricante` (obrigatório): ID do fabricante;
- `tipo` (opcional): ID do tipo de produto;
- `codigo` (opcional): código único do produto (gerado automaticamente se não fornecido);
- `entrada_cliente` (decimal, padrão 0): valor da entrada à vista;
- `valor_4_vezes` (decimal, padrão 0): valor total se parcelado em 4 vezes;
- `valor_6_vezes` (decimal, padrão 0): valor total se parcelado em 6 vezes;
- `valor_8_vezes` (decimal, padrão 0): valor total se parcelado em 8 vezes;
- `valor_10_vezes` (decimal, padrão 0): valor total se parcelado em 10 vezes;
- `valor_12_vezes` (decimal, padrão 0): valor total se parcelado em 12 vezes;
- `valor_14_vezes` (decimal, padrão 0): valor total se parcelado em 14 vezes;
- `valor_repasse_logista` (decimal, padrão 0): valor de repasse para a loja;
- `is_iphone` (boolean, padrão False): marca se é produto iPhone;
- `ativo` (boolean, padrão True): ativa/desativa produto.

Exemplo de payload:

```json
{
  "nome": "iPhone 12 Pro",
  "fabricante": 1,
  "tipo": 2,
  "entrada_cliente": "300.00",
  "valor_4_vezes": "1200.00",
  "valor_6_vezes": "1220.00",
  "valor_8_vezes": "1240.00",
  "valor_10_vezes": "1260.00",
  "valor_12_vezes": "1280.00",
  "valor_14_vezes": "1300.00",
  "valor_repasse_logista": "100.00",
  "is_iphone": true,
  "ativo": true
}
```

### `GET /api/produtos/{id}/`

Detalhe de produto, incluindo todos os campos de opções de parcelamento.

Resposta inclui:

- Dados cadastrais (nome, código, tipo, fabricante, etc.)
- Opções de parcelamento (entrada_cliente, valor_4_vezes até valor_14_vezes)
- Valor de repasse (valor_repasse_logista)
- Status (ativo, is_iphone)
- Timestamps (criado_em, atualizado_em)

### `PUT/PATCH /api/produtos/{id}/`

Atualiza produto (exige permissão `produtos.change_produto`).

Payload: mesmos campos de criação.

Observação: É possível ajustar qualquer valor de parcelamento individualmente ou em conjunto. Útil para:

- Alterar tabela de preços por número de parcelas
- Atualizar valores de entrada ou repasse
- Marcar/desmarcar como iPhone
- Mudar tipo ou fabricante associado

### `POST /api/produtos/{id}/ativar/`

Ativa produto (`ativo=True`). Exige permissão `produtos.change_produto`.

Payload: vazio.

Efeito: Produto volta a aparecer em dropdowns de criação/edição de vendas e solicitações de crédito.

### `POST /api/produtos/{id}/desativar/`

Desativa produto (`ativo=False`). Exige permissão `produtos.change_produto`.

Payload: vazio.

Efeito: Produto sai de listas normais e não aparece em novos formulários, mas vendas já criadas com o produto mantêm referência normal.

## Vendas

Rotas baseadas em `VendaViewSet`.

### `GET /api/vendas/`

Lista vendas.

Query params:

- `search` (opcional): data de venda
- `loja_id` (opcional)
- `cliente_nome` (opcional)
- `vendas_canceladas` (opcional)
- `vendas_trocadas` (opcional)

### `POST /api/vendas/`

Cria venda com itens e pagamentos. Aplica as mesmas validacoes de caixa aberto e formularios.

Payload JSON:

- `cliente` (obrigatorio)
- `vendedor` (obrigatorio)
- `observacao` (opcional)
- `itens` (obrigatorio)
- `pagamentos` (obrigatorio)

Exemplo:

```json
{
  "cliente": 1,
  "vendedor": 2,
  "observacao": "Venda via API",
  "itens": [
    {
      "produto": 10,
      "quantidade": 1,
      "valor_unitario": "1200.00",
      "valor_desconto": "0.00",
      "imei": 5
    }
  ],
  "pagamentos": [
    {
      "tipo_pagamento": 3,
      "valor": "1200.00",
      "parcelas": 1,
      "data_primeira_parcela": "2026-02-04"
    }
  ]
}
```

### `GET /api/vendas/{id}/`

Detalhe da venda, com `itens_venda` e `pagamentos`.

### `PUT/PATCH /api/vendas/{id}/`

Atualiza venda + itens + pagamentos.

Payload: mesmo formato da criacao.

### `POST /api/vendas/{id}/documentos/`

Atualiza anexos da venda.

Content-Type recomendado: `multipart/form-data`.

Campos opcionais:

- `documento_assinado`
- `foto_cliente`
- `imagem_imei`

### `POST /api/vendas/{id}/edicao-especial/`

Edicao especial de itens/pagamentos (fluxo de permissao especifica).

Payload:

- `itens`
- `pagamentos`

### `POST /api/vendas/{id}/trocar-produto/`

Troca produto da venda e marca venda como trocada.

Campos:

- `produto_atual`
- `novo_produto`
- `imei`
- `motivo` (opcional)

### `POST /api/vendas/{id}/cancelar/`

Cancela venda (`is_deleted=True`) se caixa estiver aberto.

Payload: vazio.

## Permissoes (resumo)

Cada endpoint usa as classes de permissao do modulo `api/permissions.py` e as mesmas permissoes Django do fluxo web (`vendas.*`, `produtos.*`).

## Observacoes tecnicas

- A raiz `/api/` e publica e lista os endpoints.
- A documentacao oficial interativa e `/api/docs/`.
- A especificacao OpenAPI JSON e `/api/schema/`.
- Alguns endpoints aceitam tanto JSON quanto `multipart/form-data`, mas uploads de arquivo exigem `multipart/form-data`.

## Usuários, Grupos e Permissões

Rotas baseadas em `UserViewSet`, `GroupViewSet` e `PermissionViewSet`.

### Rotas principais

- `GET /api/users/` e `GET /api/usuarios/` — lista de usuários visíveis.
- `GET /api/users/{id}/` e `GET /api/usuarios/{id}/` — detalhe de usuário.
- `POST /api/users/` e `POST /api/usuarios/` — cria usuário.
- `PATCH /api/users/{id}/` e `PATCH /api/usuarios/{id}/` — atualiza usuário (parcial).
- `GET /api/users/me/` e `GET /api/usuarios/me/` — dados do usuário autenticado.
- `GET /api/groups/` (`/api/grupos/`) — lista grupos.
- `GET /api/permissions/` (`/api/permissoes/`) — lista permissões (read-only).

### `GET /api/usuarios/`

Query params:
- `search` (opcional): filtra por `username`, `first_name` ou `email` (icontains).
- `raw=1` (opcional): quando presente retorna um array simples de objetos (sem paginação). Caso contrário, a resposta é paginada.

Exemplo de resposta (lista paginada):

```json
{
  "count": 12,
  "num_pages": 2,
  "page": 1,
  "results": [ {"id":1, "username":"jose", "email":"jose@x.com"} ]
}
```

### Criação / Atualização

Payload para `POST`/`PATCH` (exemplo):

```json
{
  "username": "ana",
  "first_name": "Ana",
  "last_name": "Silva",
  "email": "ana@example.com",
  "password": "senha_segura",
  "loja": 1,
  "groups": [2,3],
  "user_permissions": [10,11]
}
```

- Observações:
  - Em write (`POST`/`PATCH`) `groups` e `user_permissions` são arrays de IDs e substituem (set) os valores existentes.
  - `password` é write-only; em criação o campo será aplicado como senha do usuário.

### Representation (leitura)

Ao ler (`GET`) um usuário, os campos `groups` e `user_permissions` vêm como objetos aninhados (nome/descricao/id), por exemplo:

```json
{
  "id": 3,
  "username": "ana",
  "email": "ana@example.com",
  "groups": [{"id":2,"name":"VENDEDOR"}],
  "user_permissions": [{"id":10,"codename":"vendas.add_venda"}]
}
```

### Permissões

- Os endpoints de usuário usam a classe `api.permissions.UserPermission` (mapeia actions para as permissões Django `accounts.view_user`, `accounts.add_user`, `accounts.change_user`, `accounts.delete_user`).
- Superusers têm acesso total.

### Notas rápidas

- O frontend pode consumir as rotas em português (`/api/usuarios`, `/api/grupos`, `/api/permissoes`) ou em inglês (`/api/users`, `/api/groups`, `/api/permissions`).
- Use `GET /api/usuarios/?raw=1` para obter um array simples quando for necessário preencher dropdowns sem paginação.

