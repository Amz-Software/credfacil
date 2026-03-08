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

## Padrões Comuns da API

### Query Params Padrão

Os endpoints seguem padrões consistentes para filtros:

| Parâmetro | Tipo | Descrição |
|-----------|------|-----------|
| `search` | string | Busca genérica (nome, data, etc.) |
| `loja` | integer | ID da loja para filtrar |
| `status` | string | Status do registro (varia por tipo) |
| `data_inicio` | date | Filtrar registros a partir desta data (YYYY-MM-DD) |
| `data_fim` | date | Filtrar registros até esta data (YYYY-MM-DD) |

### Filtro por Loja

Todos os endpoints que suportam filtro por loja usam o parâmetro **`loja`**:

```bash
# Solicitações de uma loja específica
GET /api/solicitacoes/?loja=1

# Vendas de uma loja específica
GET /api/vendas/?loja=1

# KPIs de uma loja específica
GET /api/solicitacoes/kpis/?loja=1
```

#### Comportamento do Filtro por Loja

**Para usuários ADMIN** (com permissão `view_all_analise_credito` ou `can_view_all_sales`):
- ✅ Podem ver dados de todas as lojas
- ✅ Parâmetro `?loja=X` funciona para qualquer loja
- ✅ Se omitir `?loja`, vê dados de todas as lojas

**Para usuários NÃO-ADMIN** (vendedores, analistas):
- ✅ O backend verifica se o usuário tem acesso à loja solicitada via `user.lojas_acesso`
- ✅ Se `?loja=27` for enviado E o usuário tiver acesso à loja 27 → retorna dados da loja 27
- ⚠️ Se `?loja=27` for enviado MAS o usuário NÃO tiver acesso → ignora e usa loja da sessão
- ⚠️ Se `?loja` for omitido → usa loja da sessão (`session['loja_id']`)

**Observação para endpoints de detalhe (`.../{id}/`)**:
- Em detalhes de recurso (ex.: `GET /api/solicitacoes/{cliente_id}/`), quando `?loja=X` é enviado sem acesso, a API retorna **403** (não faz fallback silencioso)

**Exemplo prático:**
```bash
# Usuário "teste" tem acesso às lojas: [1, 27, 35]

# ✅ Funciona - usuário tem acesso à loja 27
GET /api/solicitacoes/?loja=27
# Retorna: solicitações da loja 27

# ⚠️ Não funciona - usuário NÃO tem acesso à loja 99
GET /api/solicitacoes/?loja=99
# Retorna: solicitações da loja da sessão (fallback)

# ⚠️ Sem filtro - usa loja da sessão
GET /api/solicitacoes/
# Retorna: solicitações da loja da sessão atual
```

**Importante:** O frontend deve sempre enviar o parâmetro `?loja=X` correspondente à loja selecionada pelo usuário, pois o backend valida se o usuário tem acesso via `user.lojas_acesso`.

### Paginação

Endpoints que retornam listas são paginados por padrão. A resposta inclui:

```json
{
  "count": 2036,
  "num_pages": 102,
  "page": 1,
  "results": [...]
}
```

Para obter dados sem paginação (quando disponível), use:
- `raw=1` ou `all=1` em endpoints específicos

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

- `count`: Total de registros
- `num_pages`: Número total de páginas
- `page`: Página atual
- `results`: Array com as solicitações
- `kpis`: Objeto com contadores por status de análise
- `status_choices`: Array com opções de status disponíveis
- `status_app_choices`: Array com opções de status do app

Exemplo de resposta:

```json
{
  "count": 2036,
  "num_pages": 102,
  "page": 1,
  "results": [
    {
      "id": 1,
      "nome": "João Silva",
      "cpf": "12345678900",
      "telefone": "11999999999",
      "analise_credito": {
        "id": 1,
        "status": "A",
        "status_aplicativo": "I",
        "data_analise": "2026-02-15T10:30:00Z",
        "produto": {
          "id": 5,
          "nome": "iPhone 14 Pro"
        }
      }
    }
  ],
  "kpis": {
    "EA": 41,
    "A": 1031,
    "R": 799,
    "C": 165
  },
  "status_choices": [
    ["EA", "Em análise"],
    ["A", "Aprovado"],
    ["R", "Reprovado"],
    ["C", "Cancelado"]
  ],
  "status_app_choices": [
    ["P", "Pendente"],
    ["C", "Confirmação pendente"],
    ["I", "Instalado"]
  ]
}
```

**KPIs detalhados:**
- `EA` (Em análise): Solicitações aguardando análise
- `A` (Aprovado): Análises aprovadas
- `R` (Reprovado): Análises reprovadas
- `C` (Cancelado): Análises canceladas

**Filtro por Loja:**
- **Admin**: Os KPIs respeitam o parâmetro `?loja=X` se fornecido, ou retornam dados de todas as lojas
- **Não-admin**: Os KPIs respeitam o parâmetro `?loja=X` se o usuário tiver acesso àquela loja via `user.lojas_acesso`, caso contrário usa a loja da sessão

### `GET /api/solicitacoes/kpis/`

**Endpoint dedicado** para retornar apenas os KPIs de solicitações, sem paginação ou lista de resultados.

Query params:

- `loja` (opcional): ID da loja para filtrar KPIs

Resposta:

```json
{
  "kpis": {
    "EA": 41,
    "A": 1031,
    "R": 799,
    "C": 165
  },
  "status_choices": [
    ["EA", "Em análise"],
    ["A", "Aprovado"],
    ["R", "Reprovado"],
    ["C", "Cancelado"]
  ],
  "status_app_choices": [
    ["P", "Pendente"],
    ["C", "Confirmação pendente"],
    ["I", "Instalado"]
  ]
}
```

**Vantagens:**
- ✅ Retorno ultra rápido (sem paginação)
- ✅ Ideal para dashboards e cards de KPI
- ✅ Pode filtrar por loja específica
- ✅ Respeita `user.lojas_acesso` para não-admins

**Comportamento do filtro:**
- **Admin**: Retorna KPIs de todas as lojas, ou da loja especificada em `?loja=X`
- **Não-admin**: Valida se usuário tem acesso à loja via `user.lojas_acesso`:
  - ✅ Se tiver acesso à `?loja=X` → retorna KPIs da loja X
  - ⚠️ Se não tiver acesso → retorna KPIs da loja da sessão

**Exemplos de uso:**
```bash
# Admin: KPIs de todas as lojas
GET /api/solicitacoes/kpis/

# Admin: KPIs de uma loja específica
GET /api/solicitacoes/kpis/?loja=1

# Não-admin: KPIs da loja que tem acesso
GET /api/solicitacoes/kpis/?loja=27
# (Se usuário tiver acesso à loja 27, retorna os KPIs dela)
```

**Quando usar:**
- Usar `GET /api/solicitacoes/kpis/` para atualizar apenas os contadores
- Usar `GET /api/solicitacoes/` quando precisar da lista completa com KPIs

### `GET /api/solicitacoes/{cliente_id}/`

Detalhe completo da solicitacao do cliente.

**Permissão requerida:** `vendas.view_cliente`

**Regras de acesso por loja (não-admin):**
- Se enviar `?loja=X`, o usuário precisa ter acesso a essa loja (`user.lojas`/`user.loja`), senão retorna **403**
- Se enviar `?loja=X`, a solicitação também precisa pertencer à loja `X`, senão retorna **403**
- Se não enviar `?loja`, usa loja da sessão quando disponível; sem sessão, valida pelas lojas vinculadas ao usuário

**Erros comuns:**
- `400`: parâmetro `loja` inválido
- `403`: ação não autorizada para a loja
- `404`: solicitação não encontrada

**Exemplo:**
```bash
# Vendedor com acesso à loja 27
GET /api/solicitacoes/2107/?loja=27  # ✅ se a solicitação 2107 for da loja 27

# Usuário sem acesso à loja 27
GET /api/solicitacoes/2107/?loja=27  # ❌ 403
```

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

## Parcelamentos

Rotas baseadas em `ParcelamentoViewSet`.

### `GET /api/parcelamentos/`

Lista todos os parcelamentos cadastrados.

Resposta:

```json
[
  {
    "id": 1,
    "qtd_vezes": 4,
    "porcentagem_juros": "5.00"
  },
  {
    "id": 2,
    "qtd_vezes": 6,
    "porcentagem_juros": "7.50"
  },
  {
    "id": 3,
    "qtd_vezes": 8,
    "porcentagem_juros": "10.00"
  }
]
```

### `POST /api/parcelamentos/`

Cria novo parcelamento. Exige permissão `produtos.add_produto` (via `ProdutoPermission`).

Payload:

```json
{
  "qtd_vezes": 10,
  "porcentagem_juros": "12.50"
}
```

Campos:

- `qtd_vezes` (obrigatório, único): número de parcelas
- `porcentagem_juros` (obrigatório): percentual de juros aplicado

### `GET /api/parcelamentos/{id}/`

Detalhe de um parcelamento específico.

### `PUT/PATCH /api/parcelamentos/{id}/`

Atualiza parcelamento (exige permissão `produtos.change_produto`).

Payload: mesmos campos de criação.

### `DELETE /api/parcelamentos/{id}/`

Remove parcelamento (exige permissão `produtos.delete_produto`).

**Atenção:** Apenas remova parcelamentos que não estejam sendo utilizados em vendas.

## Repasses

Rotas baseadas em `RepasseViewSet`.

Gerencia repasses agendados para pagamento às lojas.

### Permissões

- `list` e `retrieve`: exige `financeiro.view_repasse`
- `create`: exige `financeiro.add_repasse`
- `update`/`partial_update`: exige `financeiro.change_repasse` (ou staff)
- `destroy`: exige `financeiro.delete_repasse` (ou staff)

### `GET /api/repasses/`

Lista **TODOS os repasses** sem filtro de status por padrão.

Query params:

- `loja` (opcional): ID da loja para filtrar
- `status` (opcional): `pendente`, `pago` ou `cancelado` - filtra por um status específico
- `data_inicio` (opcional): data inicial para filtro (YYYY-MM-DD)
- `data_fim` (opcional): data final para filtro (YYYY-MM-DD)
- `ordering` (opcional): `data`, `-data`, `valor`, `-valor`, `status`

**Comportamento do filtro por loja:**
- **Admin**: Pode filtrar repasses de qualquer loja
- **Não-admin**: Pode filtrar apenas repasses de lojas que tem acesso via `user.lojas_acesso`

**Comportamento padrão:**
- Sem nenhum filtro: retorna **TODOS os repasses** (pendentes + pagos + cancelados)
- Com `?status=pendente`: retorna apenas repasses pendentes
- Com `?status=pago`: retorna apenas repasses pagos
- Com `?status=cancelado`: retorna apenas repasses cancelados

Resposta paginada:

```json
{
  "count": 245,
  "num_pages": 13,
  "page": 1,
  "results": [
    {
      "id": 1,
      "valor": "5000.00",
      "data": "2026-02-20T10:00:00Z",
      "status": "pendente",
      "observacao": "Repasse agendado para análise",
      "criado_por": 1,
      "criado_em": "2026-02-10T15:30:00Z"
    },
    {
      "id": 2,
      "valor": "2500.00",
      "data": "2026-01-15T10:00:00Z",
      "status": "pago",
      "observacao": "Repasse pago",
      "criado_por": 1,
      "criado_em": "2026-01-10T15:30:00Z"
    }
  ]
}
```

**Campos:**
- `id`: ID do repasse
- `valor`: Valor em decimal
- `data`: Data e hora do repasse (DateTime)
- `status`: `pendente`, `pago` ou `cancelado`
- `observacao`: Observações opcionais
- `criado_por`: ID do usuário que criou
- `criado_em`: Data de criação

### `GET /api/repasses/agendados/`

**Endpoint dedicado** para retornar repasses **calculados automaticamente** baseado nos períodos de venda (funciona igual ao sistema web normal).

**Diferencial:** Este endpoint NÃO retorna registros do banco de dados. Ele **calcula dinamicamente** os repasses baseado nas vendas realizadas em períodos específicos.

**Regras de Cálculo:**

A loja possui 3 datas de repasse por mês (dias 6, 16 e 26), cada uma com seu período de competência:

1. **Repasse do dia 6:** vendas do dia 26 do mês anterior até dia 05 do mês atual
2. **Repasse do dia 16:** vendas do dia 06 até dia 15 do mês atual  
3. **Repasse do dia 26:** vendas do dia 16 até dia 25 do mês atual

O valor de cada repasse é calculado pela soma do `repasse_logista` de todas as vendas do período.

Query params:

- `loja` (obrigatório para não-admin): ID da loja para filtrar
- `meses_atras` (opcional, padrão: 0): Quantos meses olhar para trás (máximo: 6)

Resposta: objeto com informações da loja, total de atrasados e array de repasses calculados.

Exemplo:

```bash
# Repasses calculados da loja 1 (mês atual)
GET /api/repasses/agendados/?loja=1

# Repasses dos últimos 3 meses (inclui mês atual)
GET /api/repasses/agendados/?loja=1&meses_atras=3

# Se omitir loja, usa loja da sessão (não-admin)
GET /api/repasses/agendados/
```

Resposta:

```json
{
  "loja_id": 1,
  "loja_nome": "Loja Centro",
  "meses_consultados": 0,
  "total_atrasados": 2,
  "repasses": [
    {
      "data": "2026-03-26",
      "data_formatada": "26/03/2026",
      "inicio_periodo": "2026-03-16",
      "inicio_periodo_formatado": "16/03/2026",
      "fim_periodo": "2026-03-25",
      "fim_periodo_formatado": "25/03/2026",
      "qtd_vendas": 15,
      "valor_total_repasse": "12500.50",
      "feito": false,
      "atrasado": false
    },
    {
      "data": "2026-03-16",
      "data_formatada": "16/03/2026",
      "inicio_periodo": "2026-03-06",
      "inicio_periodo_formatado": "06/03/2026",
      "fim_periodo": "2026-03-15",
      "fim_periodo_formatado": "15/03/2026",
      "qtd_vendas": 18,
      "valor_total_repasse": "15800.00",
      "feito": false,
      "atrasado": false
    },
    {
      "data": "2026-03-06",
      "data_formatada": "06/03/2026",
      "inicio_periodo": "2026-02-26",
      "inicio_periodo_formatado": "26/02/2026",
      "fim_periodo": "2026-03-05",
      "fim_periodo_formatado": "05/03/2026",
      "qtd_vendas": 12,
      "valor_total_repasse": "9500.00",
      "feito": true,
      "atrasado": false
    },
    {
      "data": "2026-02-26",
      "data_formatada": "26/02/2026",
      "inicio_periodo": "2026-02-16",
      "inicio_periodo_formatado": "16/02/2026",
      "fim_periodo": "2026-02-25",
      "fim_periodo_formatado": "25/02/2026",
      "qtd_vendas": 10,
      "valor_total_repasse": "8200.00",
      "feito": false,
      "atrasado": true
    }
  ]
}
```

**Campos da Resposta:**

- `loja_id`: ID da loja consultada
- `loja_nome`: Nome da loja
- `meses_consultados`: Quantos meses foram consultados (0 = apenas mês atual)
- `total_atrasados`: Número de repasses com `atrasado: true`
- `repasses[]`: Array com os repasses calculados:
  - `data`: Data do repasse (YYYY-MM-DD)
  - `data_formatada`: Data formatada (DD/MM/YYYY)
  - `inicio_periodo`/`fim_periodo`: Período de competência (YYYY-MM-DD)
  - `inicio_periodo_formatado`/`fim_periodo_formatado`: Período formatado (DD/MM/YYYY)
  - `qtd_vendas`: Quantidade de vendas no período
  - `valor_total_repasse`: Valor total calculado (string decimal)
  - `feito`: Se existe registro do repasse no banco (True/False)
  - `atrasado`: Se a data passou e ainda não foi feito (True/False)

**Nota Importante:** 
- Este endpoint calcula os repasses em tempo real baseado nas **vendas realizadas**
- O campo `feito` indica se existe um registro de `Repasse` no banco de dados para aquela data
- Repasses só aparecem na resposta se houver vendas no período (qtd_vendas > 0)
- Se o valor registrado no banco for menor que o calculado, o sistema automaticamente atualiza o status para `parcial`

**Para acessar registros do banco de dados** (modelo Repasse), use:
```bash
GET /api/repasses/?loja=1
GET /api/repasses/?status=pendente&loja=1
```

### `GET /api/repasses/{id}/`

Detalhe de um repasse específico.

### `POST /api/repasses/`

Cria novo repasse.

Campos obrigatórios:
- `valor` (decimal): Valor do repasse
- `data` (datetime): Data e hora do repasse
- `status` (string): `pendente`, `pago` ou `cancelado`

Campos opcionais:
- `observacao` (string): Observações sobre o repasse

Payload:

```json
{
  "valor": "5000.00",
  "data": "2026-02-20T10:00:00Z",
  "status": "pendente",
  "observacao": "Pagamento mensal - loja A"
}
```

**Nota:** O campo `loja` é determinado automaticamente com base na sessão do usuário.

### `PUT/PATCH /api/repasses/{id}/`

Atualiza repasse. Exige permissão `financeiro.change_repasse`.

Payload: mesmos campos de criação.

### `DELETE /api/repasses/{id}/`

Deleta repasse. Exige permissão `financeiro.delete_repasse`.

### Exemplos de Uso

```bash
# Listar TODOS os repasses (sem filtro)
GET /api/repasses/

# Listar apenas repasses PENDENTES
GET /api/repasses/?status=pendente

# Listar repasses PAGOS
GET /api/repasses/?status=pago

# Listar repasses CANCELADOS
GET /api/repasses/?status=cancelado

# Listar repasses de uma loja específica
GET /api/repasses/?loja=1

# Alias: Todos os repasses da loja (qualquer status)
GET /api/repasses/agendados/?loja=1

# Repasses pago em um período
GET /api/repasses/?status=pago&data_inicio=2026-01-01&data_fim=2026-01-31

# Criar novo repasse
POST /api/repasses/
Content-Type: application/json

{
  "valor": "2500.00",
  "data": "2026-03-15T10:00:00Z",
  "status": "pendente",
  "observacao": "Adiantamento para próxima venda"
}
```

## Produtos

Rotas baseadas em `ProdutoViewSet`.

### `GET /api/produtos/`

Lista produtos.

Query params:

- `search` (opcional): nome do produto

Observacao:

- usuarios com `produtos.view_all_produtos` veem ativos e inativos
- demais veem apenas `ativo=True`

**Retorno:** Cada produto retorna `tipo` e `fabricante` como objetos completos `{id, nome}` ao invés de apenas o ID.

### `POST /api/produtos/`

Cria produto. Exige permissão `produtos.add_produto`.

Payload: campos do modelo `Produto`.

Campos principais:

- `nome` (obrigatório): nome do produto;
- `fabricante` (obrigatório): ID do fabricante (inteiro);
- `tipo` (opcional): ID do tipo de produto (inteiro);
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
  - **`tipo`**: objeto com `{id, nome}` ao invés de apenas ID
  - **`fabricante`**: objeto com `{id, nome}` ao invés de apenas ID
- Opções de parcelamento (entrada_cliente, valor_4_vezes até valor_14_vezes)
- Valor de repasse (valor_repasse_logista)
- Status (ativo, is_iphone)
- Timestamps (criado_em, atualizado_em)

Exemplo de resposta:

```json
{
  "id": 1,
  "codigo": 1001,
  "nome": "iPhone 14 Pro Max",
  "tipo": {
    "id": 2,
    "nome": "Smartphone"
  },
  "fabricante": {
    "id": 1,
    "nome": "Apple"
  },
  "entrada_cliente": "500.00",
  "valor_4_vezes": "1200.00",
  "valor_6_vezes": "1250.00",
  "valor_8_vezes": "1300.00",
  "valor_10_vezes": "1350.00",
  "valor_12_vezes": "1400.00",
  "valor_14_vezes": "1450.00",
  "valor_repasse_logista": "150.00",
  "is_iphone": true,
  "ativo": true,
  "criado_em": "2026-01-15T10:30:00Z",
  "atualizado_em": "2026-02-20T14:45:00Z"
}
```

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

### Permissões e Restrições de Acesso

**Permissões necessárias:**
- `GET /api/vendas/` (list): `vendas.view_venda`
- `GET /api/vendas/{id}/` (retrieve): `vendas.view_venda`
- `GET /api/vendas/{id}/carne/`: `vendas.view_venda`
- `GET /api/vendas/{id}/contrato/`: `vendas.view_venda`
- `POST /api/vendas/`: `vendas.add_venda`
- `PUT/PATCH /api/vendas/{id}/`: `vendas.change_venda`
- `DELETE /api/vendas/{id}/`: `vendas.delete_venda`

**Regras de acesso por loja:**

| Tipo de Usuário | Acesso a Vendas |
|-----------------|-----------------|
| **Admin/Staff** | ✅ Todas as vendas (qualquer loja) |
| **Usuário com `can_view_all_sales`** | ✅ Todas as vendas (qualquer loja) |
| **Vendedor** | ✅ Apenas vendas de suas lojas vinculadas (`user.lojas` ou `user.loja`) |

**Importante para vendedores:**
- Na **listagem** (`GET /api/vendas/`): retorna apenas vendas da loja da sessão
- Em **operações específicas** (`GET /api/vendas/{id}/`, carnê, contrato): verifica se a venda pertence a uma loja vinculada ao usuário
- Se tentar acessar venda de outra loja: **retorna 403 Forbidden**

Exemplo:
```bash
# Vendedor da Loja A
GET /api/vendas/123/  # ✅ OK se venda 123 é da Loja A
GET /api/vendas/456/  # ❌ 403 se venda 456 é da Loja B
```

### Campos retornados

Ao listar ou detalhar vendas (`GET /api/vendas/` ou `GET /api/vendas/{id}/`), a API retorna:

#### Campos principais da venda:
- `id`: ID da venda
- `loja`: ID da loja
- `loja_nome`: ✅ Nome da loja (ex: "Loja A")
- `cliente`: ID do cliente
- `cliente_nome`: ✅ Nome do cliente
- `vendedor`: ID do vendedor
- `vendedor_nome`: ✅ Nome completo ou username do vendedor
- `data_venda`: Data/hora da venda (ISO 8601: "2026-03-04T15:30:00Z")
- `observacao`: Observações sobre a venda
- `repasse_logista`: Valor do repasse para o lojista
- `is_deleted`: Boolean - se a venda foi cancelada
- `is_trocado`: Boolean - se houve troca de produto

#### Anexos:
- `documento_assinado`: URL do documento assinado (se houver)
- `foto_cliente`: URL da foto do cliente (se houver)
- `imagem_imei`: URL da imagem do IMEI (se houver)

#### Valores calculados (somente leitura):
- `valor_total`: ✅ Valor total dos produtos vendidos (string decimal)
- `valor_total_pagamentos`: ✅ Valor total dos pagamentos registrados (string decimal)
- `qtd_total_parcelas`: ✅ Quantidade total de parcelas (inteiro)
- `valor_entrada_cliente`: ✅ Valor da entrada paga pelo cliente (string decimal)

#### Itens da venda (`itens_venda`):
Array de objetos com:
- `id`: ID do item
- `produto`: ID do produto
- `produto_nome`: ✅ Nome do produto
- `imei`: IMEI do aparelho (se aplicável)
- `valor_unitario`: Valor unitário (string decimal)
- `quantidade`: Quantidade (inteiro)
- `valor_desconto`: Desconto aplicado (string decimal)

#### Pagamentos (`pagamentos`):
Array de objetos com:
- `id`: ID do pagamento
- `tipo_pagamento`: ID do tipo
- `tipo_pagamento_nome`: ✅ Nome do tipo de pagamento
- `tipo_nome`: ✅ Alias de `tipo_pagamento_nome` (compatibilidade)
- `valor`: Valor do pagamento (string decimal)
- `parcelas`: Número de parcelas (inteiro)
- `data_primeira_parcela`: Data da primeira parcela (YYYY-MM-DD)
- `porcentagem_desconto`: Porcentagem de desconto aplicada
- `bloqueado`: Boolean - se o pagamento está bloqueado
- `desativado`: Boolean - se o pagamento foi desativado
- `devolucao`: Boolean - se é uma devolução
- `quitado`: Boolean - se o pagamento foi quitado
- `tipo_nome`: ✅ (Alias para compatibilidade)
- `valor`: Valor do pagamento
- `parcelas`: Número de parcelas
- `data_primeira_parcela`: Data da primeira parcela
- `porcentagem_desconto`: Desconto em %
- `bloqueado`, `desativado`, `devolucao`, `quitado`: Flags

### `GET /api/vendas/`

Lista vendas.

Query params:

- `search` (opcional): data de venda
- `loja` (opcional): id da loja
- `cliente_nome` (opcional): filtrar por nome do cliente
- `vendas_canceladas` (opcional): qualquer valor para filtrar vendas canceladas
- `vendas_trocadas` (opcional): qualquer valor para filtrar vendas com troca

**Nota:** O parâmetro legado `loja_id` também é aceito por backward compatibility.

**Filtro por Loja:**
- **Admin**: Lista vendas de todas as lojas, ou da loja especificada em `?loja=X`
- **Não-admin**: Valida se usuário tem acesso à loja via `user.lojas_acesso`:
  - ✅ Se tiver acesso à `?loja=X` → lista vendas da loja X
  - ⚠️ Se não tiver acesso → lista vendas da loja da sessão

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

Detalhe completo da venda, incluindo itens vendidos e pagamentos.

**Exemplo de resposta:**

```json
{
  "id": 1071,
  "loja": 2,
  "loja_nome": "Loja Centro",
  "cliente": 45,
  "cliente_nome": "João Silva",
  "vendedor": 3,
  "vendedor_nome": "Maria Santos",
  "data_venda": "2026-03-04T15:30:00Z",
  "observacao": "Cliente preferencial",
  "repasse_logista": "800.00",
  "documento_assinado": "/media/vendas/1071/contrato.pdf",
  "foto_cliente": "/media/vendas/1071/foto.jpg",
  "imagem_imei": "/media/vendas/1071/imei.jpg",
  "is_deleted": false,
  "is_trocado": false,
  
  // Valores calculados
  "valor_total": "3000.00",
  "valor_total_pagamentos": "3000.00",
  "qtd_total_parcelas": 6,
  "valor_entrada_cliente": "500.00",
  
  // Itens vendidos
  "itens_venda": [
    {
      "id": 234,
      "produto": 10,
      "produto_nome": "iPhone 14 Pro 256GB",
      "imei": "358240092934802",
      "valor_unitario": "3000.00",
      "quantidade": 1,
      "valor_desconto": "0.00"
    }
  ],
  
  // Pagamentos
  "pagamentos": [
    {
      "id": 189,
      "tipo_pagamento": 1,
      "tipo_pagamento_nome": "ENTRADA",
      "tipo_nome": "ENTRADA",
      "valor": "500.00",
      "parcelas": 1,
      "data_primeira_parcela": "2026-03-04",
      "porcentagem_desconto": "0.00",
      "bloqueado": false,
      "desativado": false,
      "devolucao": false,
      "quitado": true
    },
    {
      "id": 190,
      "tipo_pagamento": 3,
      "tipo_pagamento_nome": "Carnê",
      "tipo_nome": "Carnê",
      "valor": "2500.00",
      "parcelas": 6,
      "data_primeira_parcela": "2026-04-04",
      "porcentagem_desconto": "25.00",
      "bloqueado": false,
      "desativado": false,
      "devolucao": false,
      "quitado": false
    }
  ]
}
```

**Dica:** Use os campos calculados (`valor_total`, `valor_total_pagamentos`, etc) para exibir resumos sem precisar calcular no frontend.

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

### `GET /api/vendas/{id}/carne/`

Retorna **dados estruturados em JSON** do carnê/promissória para geração de PDF no frontend.

**Permissão requerida:** `vendas.view_venda`

**Query params:**
- `tipo` (opcional): `carne` ou `promissoria` (padrão: `carne`)

**Resposta:** JSON com dados estruturados

```json
{
  "venda_id": 123,
  "valor_total": "5000.00",
  "tipo_pagamento": "Carnê",
  "quantidade_parcelas": 3,
  "nome_cliente": "João Silva",
  "endereco_cliente": "Rua A, 123",
  "cpf": "123.456.789-00",
  "data_atual": "2026-03-04",
  "parcelas_info": [
    {
      "parcela": 1,
      "valor_parcela": "1666.67",
      "data_vencimento": "04/04/2026",
      "qr_code_base64": "data:image/png;base64,...",
      "chave_pix": "seu-pix@banco"
    }
  ],
  "loja": {
    "nome": "Loja A",
    "telefone": "91 3333-3333",
    "cnpj": "12.345.678/0001-90"
  }
}
```

**Como usar no Frontend:**

```javascript
// Buscar dados
const response = await fetch('/api/vendas/123/carne/', {
  headers: { 'Authorization': 'Bearer TOKEN' }
});
const data = await response.json();

// Montar HTML e gerar PDF com html2pdf.js
const html = `
  <h2>Carnê ${data.tipo_pagamento}</h2>
  <p>Cliente: ${data.nome_cliente}</p>
  <p>CPF: ${data.cpf}</p>
  <table>
    <tr>
      <th>Parcela</th>
      <th>Valor</th>
      <th>Vencimento</th>
    </tr>
    ${data.parcelas_info.map(p => `
      <tr>
        <td>${p.parcela}</td>
        <td>R$ ${p.valor_parcela}</td>
        <td>${p.data_vencimento}</td>
      </tr>
    `).join('')}
  </table>
`;

// Gerar PDF (requer html2pdf.js)
html2pdf().set(options).fromString(html).save('carne.pdf');
```

### `GET /api/vendas/{id}/contrato/`

Retorna **dados estruturados em JSON** do contrato para geração de PDF no frontend.

**Permissão requerida:** `vendas.view_venda`

**Resposta:** JSON com dados estruturados

```json
{
  "venda_id": 123,
  "valor_total": "5000.00",
  "tipo_pagamento": "Carnê",
  "cliente": {
    "nome": "João Silva",
    "cpf": "123.456.789-00",
    "rg": "1234567",
    "endereco": "Rua A, 123",
    "telefone": "91 99999-9999"
  },
  "data_atual": "2026-03-04",
  "loja": {
    "nome": "Loja A",
    "cnpj": "12.345.678/0001-90",
    "endereco": "Rua Principal, 100",
    "contrato": {
      "textos": [...],
      "clausulas": [...]
    }
  },
  "aparelho": {
    "nome": "iPhone 14 Pro",
    "imei": "358240092934802"
  },
  "valor_parcela": "1666.67",
  "quantidade_parcelas": 3,
  "parcelas_meses": ["04/04/2026", "04/05/2026", "04/06/2026"],
  "primeira_parcela": "04/04/2026",
  "ultima_parcela": "04/06/2026"
}
```

**Como usar no Frontend:**

```javascript
// Buscar dados
const response = await fetch('/api/vendas/123/contrato/', {
  headers: { 'Authorization': 'Bearer TOKEN' }
});
const data = await response.json();

// Montar HTML com os dados
const html = `
  <h2>Contrato de Venda</h2>
  <p>Cliente: ${data.cliente.nome}</p>
  <p>CPF: ${data.cliente.cpf}</p>
  <p>Loja: ${data.loja.nome}</p>
  <p>Aparelho: ${data.aparelho.nome}</p>
  <p>IMEI: ${data.aparelho.imei}</p>
  <p>Valor Total: R$ ${data.valor_total}</p>
  <p>Parcelas: ${data.quantidade_parcelas}x de R$ ${data.valor_parcela}</p>
  ${(data.loja.contrato?.textos || []).map(t => `<p>${t}</p>`).join('')}
`;

// Gerar PDF
html2pdf().set(options).fromString(html).save('contrato.pdf');
```

### Dependências de Frontend

Para gerar PDFs no frontend, use uma dessas bibliotecas:

1. **html2pdf.js** (recomendado - simples)
   ```bash
   npm install html2pdf.js
   ```

2. **jsPDF** + **html2canvas**
   ```bash
   npm install jspdf html2canvas
   ```

3. **pdfkit**
   ```bash
   npm install pdfkit
   ```

### Detalhes de Implementação

#### QR Code PIX
- ✅ **Fornecido pela API** em `parcelas_info[].qr_code_base64`
- Formato: `data:image/png;base64,...` (pronto para usar em `<img src="">`)
- Gerado automaticamente para cada parcela com:
  - Chave PIX da loja CredFacil
  - Valor exato da parcela
  - TXID único (formato: `{pagamento_id:04d}{parcela:02d}`)
  - Descrição: `"{cliente} - Parcela {n} de {total}"`

#### Logo da Empresa
- ⚠️ **NÃO fornecido pela API** (por questão de performance)
- **Recomendação**: Use logo estática no projeto frontend
- Caminho sugerido: `/assets/images/logo.png`
- Formato: PNG com fundo transparente
- Resolução recomendada: 300x100px

```javascript
// Exemplo de uso da logo
<img src="/assets/images/logo.png" alt="Logo IPIX" style="max-width: 100px;">
```

#### Texto Personalizado do Contrato
- ✅ **Fornecido pela API** em `loja.contrato`
- Formato: JSON com estrutura livre (definida por cada loja)
- Exemplo:
  ```json
  {
    "textos": [
      "4. Condições de Uso",
      "O Locatário compromete-se a...",
      "5. Penalidades",
      "Em caso de atraso..."
    ],
    "clausulas": [...]
  }
  ```
- Use `data.loja.contrato?.textos` ou `data.loja.contrato?.clausulas` conforme estrutura

#### Formato de Datas
- ✅ **Todas as datas vêm formatadas**
- Datas de vencimento: `DD/MM/YYYY` (ex: "04/04/2026")
- Data atual: `YYYY-MM-DD` ISO format (ex: "2026-03-04")
- Arrays de datas: `["04/04/2026", "04/05/2026", ...]`

**Importante:** Use as datas como vêm da API - já estão formatadas para exibição.

### Erros Possíveis

- 400: Venda não possui pagamento em carnê/promissória
- 403: Usuário não tem permissão `vendas.view_venda` **OU** não tem acesso à loja da venda
- 404: Venda não encontrada

### Restrições de Acesso

**Para vendedores (não-admin):**
- ✅ Pode acessar vendas das lojas vinculadas a ele (`user.lojas`)
- ✅ Pode acessar vendas da sua loja principal (`user.loja`)
- ❌ **Não pode** acessar vendas de outras lojas (retorna 403)

**Para admin/gerentes:**
- ✅ Acesso total a todas as vendas (qualquer loja)
- ✅ Permissão `vendas.can_view_all_sales` também dá acesso total


## Permissoes (resumo)

Cada endpoint usa as classes de permissao do modulo `api/permissions.py` e as mesmas permissoes Django do fluxo web (`vendas.*`, `produtos.*`).

## Observacoes tecnicas

- A raiz `/api/` e publica e lista os endpoints.
- A documentacao oficial interativa e `/api/docs/`.
- A especificacao OpenAPI JSON e `/api/schema/`.
- Alguns endpoints aceitam tanto JSON quanto `multipart/form-data`, mas uploads de arquivo exigem `multipart/form-data`.

## Guia Rápido: Query Params por Endpoint

**Nota sobre filtro de loja:** Para usuários não-admin, o backend valida se o usuário tem acesso à loja especificada no parâmetro `?loja=X` via `user.lojas_acesso`. Se não tiver acesso, usa a loja da sessão automaticamente.

### Solicitações (`/api/solicitacoes/`)

```bash
# Listar todas
GET /api/solicitacoes/

# Buscar por nome
GET /api/solicitacoes/?search=João

# Filtrar por status
GET /api/solicitacoes/?status=A

# Filtrar por loja
GET /api/solicitacoes/?loja=1

# Combinado
GET /api/solicitacoes/?search=João&status=A&loja=1&data_inicio=2026-01-01&data_fim=2026-02-28

# Apenas KPIs
GET /api/solicitacoes/kpis/
GET /api/solicitacoes/kpis/?loja=1
```

**Status disponíveis:** `EA` (em análise), `A` (aprovado), `R` (reprovado), `C` (cancelado)

**Status do app:** `P` (pendente), `C` (confirmação pendente), `I` (instalado)

### Vendas (`/api/vendas/`)

```bash
# Listar todas
GET /api/vendas/

# Buscar por data
GET /api/vendas/?search=2026-02-15

# Filtrar por loja
GET /api/vendas/?loja=1

# Filtrar por nome do cliente
GET /api/vendas/?cliente_nome=João

# Apenas vendas canceladas
GET /api/vendas/?vendas_canceladas=1

# Apenas vendas com troca
GET /api/vendas/?vendas_trocadas=1

# Combinado
GET /api/vendas/?loja=1&cliente_nome=João&vendas_canceladas=1

# Dados para gerar carnê (JSON)
GET /api/vendas/123/carne/
GET /api/vendas/123/carne/?tipo=promissoria

# Dados para gerar contrato (JSON)
GET /api/vendas/123/contrato/
```

### Lojas (`/api/lojas/`)

```bash
# Listar todas
GET /api/lojas/

# Buscar por nome
GET /api/lojas/?search=Loja%20A

# Filtrar por status
GET /api/lojas/?filter=pendente

# Detalhe com filtro de período
GET /api/lojas/1/?data_inicio=2026-01-01&data_fim=2026-02-28

# Detalhe com paginação
GET /api/lojas/1/?repasse_page=2&venda_page=3
```

**Filtros disponíveis:** `pendente`, `sem_pendente`

### Repasses (`/api/repasses/`)

```bash
# Listar TODOS os repasses (pendentes + pagos + cancelados)
GET /api/repasses/

# Listar apenas repasses PENDENTES
GET /api/repasses/?status=pendente

# Listar repasses PAGOS
GET /api/repasses/?status=pago

# Listar repasses de uma loja
GET /api/repasses/?loja=1

# Repasses CALCULADOS automaticamente (baseado em períodos de venda)
GET /api/repasses/agendados/?loja=1
GET /api/repasses/agendados/?loja=1&meses_atras=3

# Filtrar por período
GET /api/repasses/?data_inicio=2026-02-01&data_fim=2026-02-28

# Repasses pago em um período
GET /api/repasses/?status=pago&data_inicio=2026-01-01&data_fim=2026-01-31

# Combinado
GET /api/repasses/?loja=1&status=pendente&data_inicio=2026-02-01
```

**Status disponíveis:** `pendente`, `pago`, `cancelado`

### Produtos (`/api/produtos/`)

```bash
# Listar todos
GET /api/produtos/

# Buscar por nome
GET /api/produtos/?search=iPhone
```

### Usuários (`/api/usuarios/` ou `/api/users/`)

```bash
# Listar todos (paginado)
GET /api/usuarios/

# Buscar por nome, email ou username
GET /api/usuarios/?search=joão

# Lista simples (sem paginação)
GET /api/usuarios/?raw=1
```

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

## Controle de Acesso por Loja (lojas_acesso)

### Como funciona o acesso a lojas

O sistema utiliza o relacionamento `User.lojas` (many-to-many) para determinar quais lojas um usuário pode acessar.

**No login (`POST /api/token/`)**, o backend retorna:
```json
{
  "user": {
    "loja": 1,                    // ID da loja principal (FK)
    "loja_principal": {           // Objeto completo da loja principal
      "id": 1,
      "nome": "Loja A",
      "cnpj": "12345678000190"
    },
    "lojas_acesso": [             // ⭐ Todas as lojas que usuário pode acessar
      {
        "id": 1,
        "nome": "Loja A",
        "cnpj": "12345678000190"
      },
      {
        "id": 27,
        "nome": "CONNECT mocajuba",
        "cnpj": "98765432000110"
      },
      {
        "id": 35,
        "nome": "Loja Filial Sul",
        "cnpj": "11223344000155"
      }
    ]
  }
}
```

### Validação no Backend

Quando um endpoint recebe o parâmetro `?loja=X`:

1. **Se usuário tem permissão `view_all_*`** (admin):
   - ✅ Aceita qualquer loja
   - Retorna dados da loja solicitada

2. **Se usuário NÃO tem permissão `view_all_*`** (vendedor/analista):
   - ✅ Verifica se `X` está em `user.lojas.all()`
   - ✅ Se SIM → retorna dados da loja X
   - ⚠️ Se NÃO → ignora `?loja=X` e usa `session['loja_id']`

### Endpoints Afetados

Todos os endpoints que suportam filtro `?loja=`:
- `GET /api/solicitacoes/` (listagem de solicitações)
- `GET /api/solicitacoes/kpis/` (KPIs de solicitações)
- `GET /api/vendas/` (listagem de vendas)

### Exemplo Prático

**Cenário:** Usuário "teste" tem `lojas_acesso = [1, 27, 35]`

```bash
# ✅ Caso 1: Loja permitida
GET /api/solicitacoes/?loja=27
# Backend valida: 27 in [1, 27, 35] → TRUE
# Retorna: Solicitações da loja 27

# ⚠️ Caso 2: Loja NÃO permitida
GET /api/solicitacoes/?loja=99
# Backend valida: 99 in [1, 27, 35] → FALSE
# Retorna: Solicitações da loja da sessão (fallback)

# ⚠️ Caso 3: Sem filtro
GET /api/solicitacoes/
# Backend usa: session['loja_id']
# Retorna: Solicitações da loja da sessão
```

### Configuração no Admin Django

Para adicionar acesso de um usuário a múltiplas lojas:

1. Acesse o admin Django em `/admin/`
2. Vá em **Usuários** e selecione o usuário
3. Na seção **Lojas**, adicione as lojas no campo **Lojas** (many-to-many)
4. Salve

**Importante:** O campo `User.loja` (FK) define a loja "principal", mas é o relacionamento `User.lojas` (M2M) que determina **todas as lojas que o usuário pode filtrar**.

