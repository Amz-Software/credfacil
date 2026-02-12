# CredFacil API

Documentacao da API REST do projeto, com base na implementacao atual em `api/urls.py`, `api/views.py` e `core/urls.py`.

## Base URL

- Prefixo da API: `/api/`
- Health check: `GET /api/health/`
- OpenAPI (JSON): `GET /api/schema/`
- Swagger UI: `GET /api/docs/`

## Autenticacao

A API aceita dois modos:

- JWT Bearer token
- Sessao do Django (cookie de login)

### JWT

- Obter token: `POST /api/token/`
- Renovar token: `POST /api/token/refresh/`

Exemplo para obter token:

```json
{
  "username": "seu_usuario",
  "password": "sua_senha"
}
```

Exemplo de uso no header:

```http
Authorization: Bearer <access_token>
```

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
