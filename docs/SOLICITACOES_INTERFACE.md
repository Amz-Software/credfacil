# Interface de Solicitações (Novo Fluxo por Marca)

Este documento descreve como a interface de criação/edição de solicitações deve funcionar no fluxo novo:

1. Selecionar marca
2. Selecionar produto da marca
3. Preencher dados da solicitação

---

## 1) Fluxo de tela (ordem obrigatória)

## Etapa 1 — Seleção de marca

- Campo obrigatório: `marca`
- Fonte de dados: `GET /api/marcas/`
- Comportamento esperado:
  - usuário não avança sem selecionar marca
  - troca de marca limpa o campo de produto selecionado

## Etapa 2 — Seleção de produto

- Campo obrigatório: `produto`
- Fonte de dados (recomendado):
  - `GET /api/produtos/?marca=<id_marca>`
  - ou `GET /api/marcas/{id}/produtos/`
- Regras:
  - mostrar apenas produtos da marca selecionada
  - backend valida `produto.marca_id == marca`

## Etapa 3 — Dados da solicitação

- Usuário preenche dados cadastrais, contatos, comprovantes e análise de crédito.
- Envio principal:
  - criação: `POST /api/solicitacoes/`
  - edição: `PUT/PATCH /api/solicitacoes/{cliente_id}/`

---

## 2) Campos necessários por bloco

## 2.1 Cliente (obrigatórios)

- `nome`
- `telefone`
- `cpf`
- `nascimento`
- `rg`
- `cep`
- `endereco`
- `bairro`
- `cidade`
- `profissao`
- `quantidade_dependentes`
- `recebe_auxilio`
- `total_renda`

## 2.2 Contato adicional

Obrigatórios:
- `nome_adicional`
- `contato`
- `endereco_adicional`

Opcional:
- `obteve_contato`

## 2.3 Informação pessoal

Obrigatórios:
- `nome_pessoal`
- `contato_pessoal`
- `endereco_pessoal`

Opcional:
- `obteve_contato_pessoal`

## 2.4 Comprovantes

Obrigatórios:
- `documento_identificacao_frente`
- `documento_identificacao_verso`
- `comprovante_residencia`
- `foto_cliente`

Opcionais:
- `consulta_serasa`
- `restricao`

## 2.5 Análise de crédito (novo fluxo)

Obrigatórios:
- `marca`
- `produto`
- `data_pagamento`
- `numero_parcelas`

Opcionais:
- `entrada_informada`
- `analise_online`
- `email_icloud`
- `senha_icloud`

---

## 3) Regras e validações de negócio

## 3.1 Marca x produto

- `marca` é obrigatória.
- `produto` deve pertencer à `marca` selecionada.
- Erro esperado quando houver divergência:
  - `O produto informado nao pertence a marca selecionada.`

## 3.2 Parcelamento por marca (iPhone)

Para produtos iPhone:

- produto deve possuir marca vinculada
- deve existir configuração em `Parcelamento` para:
  - a marca do produto
  - a quantidade de parcelas informada

Erros comuns:
- `Nenhum parcelamento cadastrado para a marca 'X'.`
- `Parcelamento de Nx nao cadastrado para a marca 'X'.`

## 3.3 Campos condicionais de iPhone

- `entrada_informada`: usado no fluxo de iPhone (entrada mínima por produto)
- `email_icloud` e `senha_icloud`: campos condicionais conforme fluxo/permissão

## 3.4 Conflitos entre blocos de contato

Não podem ser iguais entre si:

- `contato` e `contato_pessoal`
- `endereco_adicional` e `endereco_pessoal`
- `nome_adicional` e `nome_pessoal`

---

## 4) Fluxo resumido para frontend

1. Carregar marcas
2. Usuário escolhe marca
3. Carregar produtos da marca
4. Usuário escolhe produto
5. Carregar/filtrar parcelas da marca (opcional de UX): `GET /api/parcelamentos/?marca=<id_marca>`
6. Usuário preenche os demais campos
7. Enviar `multipart/form-data` para criação/edição

---

## 5) Exemplo mínimo de payload (criação)

```json
{
  "marca": 1,
  "produto": 10,
  "numero_parcelas": "6",
  "data_pagamento": "10",
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
  "analise_online": false
}
```

Observação: para envio real, incluir também os arquivos obrigatórios de comprovante em `multipart/form-data`.
