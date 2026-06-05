# CLAUDE.md — CredFacil: Documentação do Sistema

## Visão Geral

**CredFacil** é um sistema Django + Django REST Framework (DRF) para gestão de vendas em lojas de varejo, análise de crédito de clientes e controle de repasses para logistas.

**Stack**:
- Django 4.2 + Django REST Framework
- Autenticação: Simple JWT + Session
- WebSocket: Django Channels + Redis
- Banco: SQLite (dev) / MySQL (prod)
- Docs: drf_spectacular (OpenAPI/Swagger)
- Timezone: `America/Belem` | Idioma: `pt-br`

---

## Estrutura de Apps

| App | Responsabilidade |
|-----|-----------------|
| `accounts` | Usuários, autenticação, grupos e permissões |
| `vendas` | Lojas, clientes, vendas, pagamentos, caixa, análise de crédito |
| `financeiro` | Caixa mensal, gastos, repasses ao logista |
| `produtos` | Catálogo de produtos |
| `estoque` | Controle de estoque com rastreamento por IMEI |
| `assistencia` | Ordens de serviço |
| `notificacao` | Notificações push e WebSocket |
| `api` | Endpoints REST centralizados para consumo externo |
| `core` | Configurações do projeto |

---

## Modelos e Relacionamentos

### Hierarquia de Modelos Base

Todos os modelos principais estendem uma classe `Base` abstrata com:
- `criado_em`, `modificado_em` — timestamps automáticos
- `criado_por`, `modificado_por` — FK para `User`
- `loja` — FK para `Loja`

### Diagrama de Relacionamentos

```
User (AbstractUser)
├── email (único)
├── grupos (M2M → Group)
└── loja (FK → Loja, nullable)

Loja
├── usuarios (M2M ↔ User)
├── gerentes (M2M ↔ User)
├── produtos_bloqueados (M2M ↔ Produto)
├── porcentagem_desconto_{4,6,8,10} — descontos por parcelamento IPX
├── pode_vender_iphone (bool)
└── repasses (reverse FK ← Repasse)

Cliente
├── informacao_pessoal (O2O → InformacaoPessoal)
├── contato_adicional (O2O → ContatoAdicional)
├── comprovantes (O2O → ComprovantesCliente)
└── analise_credito (O2O ← AnaliseCreditoCliente)

AnaliseCreditoCliente
├── cliente (O2O → Cliente)
├── produto (FK → Produto)
├── imei (FK → EstoqueImei, nullable)
├── venda (FK → Venda, nullable)
└── aprovado_por (FK → User)

Venda
├── cliente (FK → Cliente)
├── vendedor (FK → User)
├── caixa (FK → Caixa)
├── repasse_logista (Decimal)
├── is_deleted (bool — soft delete)
├── is_trocado (bool)
├── itens_venda (reverse FK ← ProdutoVenda)
└── pagamentos (reverse FK ← Pagamento)

ProdutoVenda
├── produto (FK → Produto)
├── venda (FK → Venda)
├── quantidade, valor_unitario, valor_desconto
└── imei (CharField — string, não FK)

Pagamento
├── venda (FK → Venda)
├── tipo_pagamento (FK → TipoPagamento)
├── valor, parcelas
└── parcelas_pagamento (reverse FK ← Parcela)

Parcela
├── pagamento (FK → Pagamento)
├── numero, valor, vencimento, data_pagamento
└── tipo_pagamento (FK → TipoPagamento)

Produto
├── valor_repasse_logista (base do cálculo de repasse)
├── entrada_cliente (valor de entrada para financiamento)
├── valor_{4,6,8,10,12,14}_vezes (preços por parcelamento)
├── is_iphone (bool — fluxo especial)
├── ativo (bool — soft delete)
└── lojas_bloqueadas (M2M ↔ Loja)

EstoqueImei
├── produto (FK → Produto)
├── produto_entrada (FK → ProdutoEntrada)
├── imei (CharField)
├── vendido, cancelado, aplicativo_instalado (bool)
└── id_venda (property → Venda)

Repasse (financeiro)
├── loja (FK → Loja)
├── valor, data
├── status: 'pendente' | 'pago' | 'cancelado'
└── criado_por, atualizado_por (FK → User)
```

---

## Fluxo de Venda (Rota 1 — Manual)

**Pré-requisito**: usuário com `vendas.add_venda` e caixa aberto.

```
1. Seleção do cliente (busca ou criação)
2. Seleção do vendedor e loja (da sessão)
3. Adição de itens (ProdutoVenda)
   └── Produto + quantidade + valor_unitario + desconto + IMEI
4. Adição de pagamentos (Pagamento)
   └── Tipo + valor + parcelas + data_primeira_parcela
   └── Soma dos pagamentos deve igualar total da venda
5. Upload opcional de documentos (contrato, foto do cliente, imagem IMEI)
6. Salvamento:
   └── Cria Venda (repasse_logista calculado automaticamente)
   └── Cria ProdutoVenda para cada item
   └── Cria Pagamento + Parcelas (datas calculadas)
   └── Move arquivos de temp/ para vendas/{pk}/
```

**Cálculo do repasse_logista**:
```python
repasse_logista = sum(item.produto.valor_repasse_logista * item.quantidade for item in itens)
```

**Geração de parcelas** (`criar_parcelas`):
- Percorre o número de parcelas
- Ajusta o dia do mês para dias válidos (ex: 30/fev → 28/fev)
- Cria cada `Parcela` com `vencimento` calculado mensalmente

---

## Fluxo de Venda (Rota 2 — Via Análise de Crédito)

Este é o fluxo principal do produto CredFacil (financiamento próprio).

```
[CLIENTE]
  └─ Vendedor cria AnaliseCreditoCliente com:
     └─ Dados do cliente (Cliente)
     └─ Produto escolhido
     └─ Status inicial: Em Análise (EA)

[ANALISTA]
  └─ Revisa a solicitação
  └─ Aprova → status: Aprovado (A)
     └─ Informa IMEI disponível
  └─ Reprova → status: Reprovado (R)
  └─ Cancela → status: Cancelado (C)

[GERAÇÃO DA VENDA] POST /api/solicitacoes/{id}/gerar-venda/
  └─ Cria Venda com cliente da análise
  └─ Cria ProdutoVenda com produto e IMEI da análise
  └─ Cria Pagamento ENTRADA (produto.entrada_cliente)
  └─ Cria Pagamento IPX com:
     └─ valor = total - entrada
     └─ parcelas = escolhido pelo analista
     └─ desconto = loja.porcentagem_desconto_{n}x
     └─ data_primeira_parcela = dia 1, 10 ou 20 do mês seguinte
  └─ Vincula analise.venda = venda criada
```

### Fluxo Especial — iPhone

Para produtos com `is_iphone = True`, o cálculo de valor e repasse é completamente diferente:

```
1. Vendedor cadastra credenciais iCloud
   └─ icloud_configurado_vendedor = True

2. Analista confirma iCloud
   └─ icloud_confirmado_analista = True

3. Analista informa IMEI (após confirmar iCloud)
   └─ analise.imei = EstoqueImei selecionado
   └─ imei.aplicativo_instalado = True

4. Operador informa entrada_informada (editável, deve ser >= produto.entrada_cliente)

5. Aprovação e geração da venda via gerar_venda:
   └─ Busca Parcelamento.objects.get(qtd_vezes=parcelas) → porcentagem_juros
   └─ valor_total = produto.valor + (produto.valor × porcentagem_juros / 100)
   └─ repasse_logista = produto.valor − entrada_informada
   └─ Pagamento ENTRADA = entrada_informada (informada pelo operador)
   └─ Pagamento IPX = valor_total (parcelado em n vezes, sem desconto de loja)
```

#### Comparativo iPhone × Não iPhone

| Campo | Não iPhone | iPhone |
|-------|-----------|--------|
| Valor do produto IPX | `produto.valor_{n}x` | `produto.valor × (1 + juros%)` |
| Repasse logista | `produto.valor_repasse_logista` | `produto.valor − entrada_informada` |
| Entrada | `produto.entrada_cliente` (fixo) | `analise.entrada_informada` (editável, ≥ mínimo) |
| Desconto de loja | `credfacil.porcentagem_desconto_{n}x` | Não aplicado |
| Juros | Embutido no `valor_{n}x` | `Parcelamento.porcentagem_juros` |

---

## Fluxo de Repasse ao Logista

### Conceito

O **repasse** é o valor que a CredFacil deve transferir ao logista (dono da loja parceira) referente às vendas realizadas em sua loja.

### Calendário de Repasses

| Data do Repasse | Competência (vendas do período) |
|----------------|--------------------------------|
| Dia 6 | 26 do mês anterior → 5 do mês atual |
| Dia 16 | 6 → 15 do mês atual |
| Dia 26 | 16 → 25 do mês atual |

### Cálculo

```python
# Em Loja.calcular_valor_repasse(data_inicio, data_fim)
valor = Venda.objects.filter(
    loja=self,
    data_venda__range=(data_inicio, data_fim),
    is_deleted=False
).aggregate(total=Sum('repasse_logista'))['total']
```

### Criação de Repasse

Via `POST /api/lojas/{id}/repasses/`:
```json
{
  "valor": "2500.00",
  "data": "2024-02-06",
  "status": "pendente",
  "observacao": "Repasse quinzena 26/01 a 05/02"
}
```

### Status do Repasse

```
pendente → pago
pendente → cancelado
```

### Verificação de Repasses Pendentes

`Loja.get_repasses_status()` retorna para cada período:
- `data` — data programada do repasse
- `inicio_periodo` / `fim_periodo` — competência
- `qtd_vendas` — quantidade de vendas no período
- `valor_total_repasse` — soma dos repasses das vendas
- `feito` — se existe `Repasse` registrado para este período
- `atrasados` — quantidade de repasses pendentes em atraso

**QuerySets especiais**:
- `Loja.objects.com_repasse_pendente()` — lojas com repasse atrasado
- `Loja.objects.sem_repasse_pendente()` — lojas em dia

---

## Autenticação e Permissões

### Métodos de Autenticação

| Método | Uso |
|--------|-----|
| Session | Interface web Django |
| JWT | API REST externa |

**Tokens JWT**:
- Access token: 15 minutos
- Refresh token: 7 dias

### Grupos de Usuários

- `VENDEDOR` — realiza vendas, cadastra clientes/análises
- `ANALISTA` — aprova/reprova análises de crédito
- `ADMINISTRADOR` — gestão completa

### Permissões Relevantes

| Permissão | Descrição |
|-----------|-----------|
| `vendas.add_venda` | Criar venda |
| `vendas.change_venda` | Editar venda |
| `vendas.can_edit_finished_sale` | Editar venda finalizada |
| `vendas.can_edit_imei_valores_venda` | Edição especial (IMEI/valores) |
| `vendas.can_view_all_stores` | Ver todas as lojas |
| `vendas.can_view_all_sales` | Ver vendas de todas as lojas |
| `vendas.change_status_analise` | Aprovar/reprovar análise |
| `vendas.view_all_analise_credito` | Ver todas as análises |
| `financeiro.view_repasse` | Ver repasses |
| `financeiro.add_repasse` | Criar repasse |
| `financeiro.change_repasse` | Editar repasse |

### Escopo por Loja (Multi-Tenant)

- Usuário pode pertencer a múltiplas lojas (M2M)
- Sessão rastreia a loja selecionada (`session['loja_id']`)
- `LojaMiddleware` injeta `loja_id` no request
- Queries são filtradas automaticamente pela loja, exceto se o usuário tiver permissão `can_view_all_*`

### Login JWT — Resposta Expandida

`POST /api/token/` retorna além dos tokens:
- Dados do usuário (id, username, nome, email)
- Grupos com permissões aninhadas
- Todas as permissões efetivas
- Flags de UI (pode_criar_venda, pode_editar_loja, etc.)
- Lojas às quais o usuário pertence (como usuário e como gerente)

---

## Endpoints da API

### Autenticação
```
POST /api/token/                    Login (retorna access + refresh + user data)
POST /api/token/refresh/            Renovar access token
```

### Lojas
```
GET    /api/lojas/                  Listar lojas
POST   /api/lojas/                  Criar loja
GET    /api/lojas/{id}/             Detalhe da loja
PATCH  /api/lojas/{id}/             Atualizar loja
GET    /api/lojas/{id}/repasses/    Listar repasses da loja
POST   /api/lojas/{id}/repasses/    Criar repasse
POST   /api/lojas/{id}/replicar-qrcode/  Replicar QR code para outras lojas
```

### Solicitações (Análise de Crédito)
```
GET    /api/solicitacoes/                       Listar análises
POST   /api/solicitacoes/                       Criar análise + cliente
GET    /api/solicitacoes/{id}/                  Detalhe
PATCH  /api/solicitacoes/{id}/                  Atualizar
POST   /api/solicitacoes/{id}/aprovar/          Aprovar análise
POST   /api/solicitacoes/{id}/reprovar/         Reprovar análise
POST   /api/solicitacoes/{id}/cancelar/         Cancelar análise
POST   /api/solicitacoes/{id}/gerar-venda/      Gerar venda a partir da análise
POST   /api/solicitacoes/{id}/imei-telefone/    Informar IMEI/telefone
POST   /api/solicitacoes/{id}/status-app/       Atualizar status do app
POST   /api/solicitacoes/{id}/instalar-app/     Marcar app instalado
POST   /api/solicitacoes/{id}/confirmar-app/    Confirmar instalação do app
POST   /api/solicitacoes/{id}/configurar-icloud/         Configurar iCloud (vendedor)
POST   /api/solicitacoes/{id}/analista-confirm-icloud/   Confirmar iCloud (analista)
POST   /api/solicitacoes/{id}/informar-imei-analise/     Analista informa IMEI
```

### Vendas
```
GET    /api/vendas/                     Listar vendas
POST   /api/vendas/                     Criar venda
GET    /api/vendas/{id}/                Detalhe
PATCH  /api/vendas/{id}/                Atualizar venda
PATCH  /api/vendas/{id}/documentos/     Upload de documentos
PATCH  /api/vendas/{id}/edicao-especial/  Edição especial (IMEI/valores)
POST   /api/vendas/{id}/trocar-produto/ Troca de produto
POST   /api/vendas/{id}/cancelar/       Cancelar venda (soft delete)
```

### Produtos
```
GET    /api/produtos/           Listar produtos
POST   /api/produtos/           Criar produto
GET    /api/produtos/{id}/      Detalhe
PATCH  /api/produtos/{id}/      Atualizar produto
POST   /api/produtos/{id}/ativar/    Ativar produto
POST   /api/produtos/{id}/desativar/ Desativar produto
```

### Usuários e Permissões
```
GET    /api/users/          Listar usuários
POST   /api/users/          Criar usuário
GET    /api/users/{id}/     Detalhe
PATCH  /api/users/{id}/     Atualizar
GET    /api/users/me/       Usuário atual
GET    /api/groups/         Listar grupos
GET    /api/permissions/    Listar permissões
```

### Utilitários
```
GET    /api/schema/   Schema OpenAPI (JSON)
GET    /api/docs/     Documentação Swagger UI
GET    /api/health/   Health check
```

---

## Padrões do Sistema

### Soft Delete

- `Venda.is_deleted = True` — venda cancelada, não apagada
- `Produto.ativo = False` — produto desativado
- Queries sempre filtram: `.filter(is_deleted=False)` ou `.filter(ativo=True)`
- IMEI **não** é restaurado ao cancelar uma venda

### Rastreamento de Usuário (Auditoria)

Todos os modelos que estendem `Base` rastreiam:
```python
model.save(user=request.user)  # popula criado_por / modificado_por
```

### Upload de Arquivos

1. Upload temporário para `vendas/temp/`
2. Após criação da Venda (com PK definido), arquivos são movidos para `vendas/{pk}/`
3. Limpeza automática no `Venda.save()` pós-insert

### Geração de Parcelas

```python
# Função criar_parcelas(pagamento, loja)
for i in range(pagamento.parcelas):
    vencimento = calcular_data_vencimento(data_base, i)
    # Ajusta dias inválidos: 30/fev → 28/fev, etc.
    Parcela.objects.create(
        pagamento=pagamento,
        numero=i+1,
        valor=pagamento.valor / pagamento.parcelas,
        vencimento=vencimento
    )
```

### Tipos de Pagamento (TipoPagamento)

Flags que controlam comportamento:
| Flag | Descrição |
|------|-----------|
| `caixa` | Lançado no caixa físico |
| `parcelas` | Permite parcelamento |
| `financeira` | Modalidade de financiamento externo |
| `carne` | Pagamento em carnê |
| `nao_contabilizar` | Não conta no saldo do caixa |

**Tipos principais**:
- `ENTRADA` — Valor de entrada pago pelo cliente
- `IPX` — Financiamento CredFacil (parcelado)

### Bloqueio de Produtos por Loja

- `Loja.produtos_bloqueados` (M2M) — produtos que a loja não pode vender
- `Loja.pode_vender_iphone` (bool) — habilita/desabilita venda de iPhones
- Verificado na criação da análise de crédito

### Numeração Automática

- Entradas de estoque: formato `ENT{ano}-{sequencial:04d}` (ex: `ENT2024-0001`)
- Usuários: username auto-gerado a partir de nome + sobrenome

### Descontos por Parcelamento (IPX — somente não iPhone)

Configurado por loja:
```
Loja.porcentagem_desconto_4x   → 4 parcelas
Loja.porcentagem_desconto_6x   → 6 parcelas
Loja.porcentagem_desconto_8x   → 8 parcelas
Loja.porcentagem_desconto_10x  → 10 parcelas
```

Aplicado no `gerar_venda` apenas para produtos **não iPhone**.

### Tabela de Parcelamento (somente iPhone)

`Parcelamento` define os juros por quantidade de parcelas para produtos iPhone:

| Campo | Descrição |
|-------|-----------|
| `qtd_vezes` | Quantidade de parcelas (unique) |
| `porcentagem_juros` | % de juros aplicado sobre `produto.valor` |

**Endpoint**: `GET/POST/PATCH/DELETE /api/parcelamentos/`

O campo `produto.valor` é o valor base do iPhone; os campos `valor_4_vezes`...`valor_14_vezes` e `valor_repasse_logista` **não são usados** para iPhones.

---

## Serializers Principais

| Serializer | Propósito |
|-----------|-----------|
| `VendaSerializer` | Leitura completa de venda com itens e pagamentos |
| `VendaCreateUpdateSerializer` | Input para criar/editar venda (aninhado) |
| `VendaEdicaoEspecialInputSerializer` | Edição especial de IMEI/valores |
| `ClienteSolicitacaoSerializer` | Criação de cliente + análise de crédito |
| `AnaliseCreditoClienteSerializer` | Análise com valores de display |
| `LojaSerializer` | Loja com usuários e gerentes aninhados |
| `LojaListSerializer` | Loja com KPIs e info de repasses |
| `RepasseSerializer` | Leitura de repasse |
| `RepasseCreateSerializer` | Input para criar repasse |
| `CustomTokenObtainPairSerializer` | Login com dados completos do usuário |
| `UserSerializer` | Usuário com grupos, permissões, lojas e flags de UI |

---

## Configuração e Variáveis de Ambiente

```bash
SECRET_KEY=...
DEBUG=True              # padrão: True
ALLOWED_HOSTS=...

# Banco de dados
DB_USED=sqlite          # 'sqlite' ou 'mysql'
DB_NAME=...             # apenas mysql
DB_USER=...
DB_PASSWORD=...
DB_HOST=...
DB_PORT=...

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

---

## Notificações em Tempo Real

- Biblioteca: `django-notifications-hq`
- WebSocket via Django Channels + Redis
- Função `enviar_ws_para_usuario(user, payload)` para push em tempo real
- Acionado em: mudanças de status de análise, criação de vendas, etc.

---

## Fluxo de Requisição Completo

```
Cliente HTTP
    │
    ▼
Django Router (urls.py)
    │
    ├─ /api/* → api/urls.py → DefaultRouter → ViewSet
    │                              │
    │                              ├─ Permission checks (DRF + custom)
    │                              ├─ Serializer.is_valid()
    │                              ├─ Business logic (create/update/action)
    │                              └─ Serializer(instance).data → Response
    │
    └─ /* → Templates Django (interface web)
               │
               └─ LojaMiddleware → injeta loja_id no request
```

### Exemplo: Gerar Venda a partir de Análise

```
POST /api/solicitacoes/{id}/gerar-venda/

1. SolicitacaoViewSet.gerar_venda()
2. Busca AnaliseCreditoCliente (loja do request)
3. Valida: status == 'Aprovado', imei definido, venda não gerada
4. Cria Venda (cliente, vendedor, loja, caixa)
5. Cria ProdutoVenda (produto, imei, valor baseado no plano)
6. Cria Pagamento ENTRADA (produto.entrada_cliente, 1 parcela)
7. Cria Pagamento IPX (valor restante, n parcelas, desconto da loja)
8. Chama criar_parcelas() para cada pagamento
9. Vincula analise.venda = venda criada
10. Retorna VendaSerializer(venda).data → 201 Created
```
