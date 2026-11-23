# Contrato da API — Catálogo (`/api/bo/v1/catalogo/`)

Sessão do backoffice + CSRF (`X-CSRFToken`) em toda mutação. Cabeçalho opcional `X-Loja: <id>|todas`
(loja fora do escopo → 403). Erros no contrato `{"erro": {"codigo", "mensagem", "campos"}}`.
Listas: `{count, page, page_size, total_pages, results}` com `?page=`, `?page_size=` (máx. 100).
Valores monetários e percentuais são strings decimais (`"1000.00"`). Método sem rota → 405 `metodo_nao_permitido`
(também para GET em ações). PUT não existe: use PATCH.

Os campos legados de produto (`valor_{n}_vezes`, `valor_repasse_logista`) **nunca** são expostos.

## Escopo de loja
- **Produtos:** com `produtos.view_all_produtos` vê todos (ativos e inativos). Sem ela, só os **ativos permitidos**
  para as lojas da requisição (`Loja.produtos_permitidos_qs`: iPhone só em loja que vende iPhone, produtos
  bloqueados da loja e lojas permitidas da marca). Produto fora disso → 404.
- **Marcas:** visíveis as sem lojas permitidas (todas as lojas) ou liberadas para alguma loja da requisição.
  Acesso global (`vendas.can_view_all_stores`/superusuário) sem `X-Loja` vê todas. Marca fora disso → 404.
- **Parcelamentos:** os de marcas visíveis (ou sem marca).
- **Tipos:** catálogo global, sem escopo.

---

## Produtos

### `GET produtos/` — `produtos.view_produto`
Query: `busca` (nome contém ou código exato), `marca` (id), `ativo` (`sim|nao|todos`; só vale com
`view_all_produtos`, padrão `todos`; sem ela sempre só ativos), `ordenar` (`nome|codigo|valor|entrada_cliente|criado_em`,
`-` para decrescente; padrão `nome`).
```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [
  {"id": 7, "codigo": 12, "nome": "Galaxy A15", "valor": "1000.00", "entrada_cliente": "200.00",
   "marca": {"id": 2, "nome": "Samsung", "cor": "#1428a0", "icone": "bx bx-mobile"},
   "tipo": {"id": 1, "nome": "Celular"}, "is_iphone": false, "ativo": true}]}
```
Erros: 400 `validacao` (`campos.ativo`, `campos.marca`, `campos.ordenar`), 403.

### `GET produtos/{id}/` — `produtos.view_produto`
Lista + `criado_em`, `modificado_em`, `criado_por`, `modificado_por` (nomes) e `simulacao` (entrada mínima):
```json
{"...": "...", "simulacao": {"valor": "1000.00", "entrada": "200.00", "aviso": null, "opcoes": [
  {"qtd_vezes": 4, "porcentagem_juros": "20.00", "porcentagem_desconto": "5.00",
   "valor_financiado": "800.00", "valor_total": "960.00", "valor_parcela": "240.00"}]}}
```
`aviso` vem preenchido (e `opcoes: []`) quando o produto não tem valor base ou a marca não tem parcelamento.
A conta é a mesma da geração da venda (`vendas.services.venda.calcular_valores_venda`).

### `GET produtos/{id}/simulacao/?entrada=400.00` — `produtos.view_produto`
Mesmo formato de `simulacao`, com a entrada informada (padrão: entrada mínima).
Erros: 400 `campos.entrada` (inválida ou maior que o valor), 422 `regra_de_negocio` (entrada menor que a mínima,
produto sem valor base).

### `POST produtos/` — `produtos.add_produto`
```json
{"nome": "Moto G", "valor": "1500.00", "entrada_cliente": "300.00", "tipo": 1, "marca": 2, "is_iphone": false}
```
`nome` obrigatório; `valor` opcional (≥ 0); `entrada_cliente` ≥ 0 e ≤ `valor`; `marca` precisa estar visível.
`codigo` é gerado. A loja de `X-Loja` (se for um id) fica gravada no produto. Resposta 201 = detalhe.
Erros: 400 (`campos.nome`, `valor`, `entrada_cliente`, `marca`, `tipo`), 403.

### `PATCH produtos/{id}/` — `produtos.change_produto`
Mesmos campos do POST, todos opcionais. Resposta 200 = detalhe.

### `POST produtos/{id}/ativar/` · `POST produtos/{id}/desativar/` — `produtos.delete_produto`
Corpo opcional `{"motivo": "Fora de linha"}`. Auditado (`produto_ativado`/`produto_desativado`). Idempotente.
Resposta 200 = detalhe. Quem não tem `view_all_produtos` não enxerga inativos, então não consegue ativá-los (404).

### `GET produtos/relatorio.pdf` — `produtos.view_produto`
Mesmos filtros e ordenação da lista. `application/pdf` (inline, `produtos.pdf`), mesmo layout da tela Django.

---

## Tipos de produto (sem exclusão)

### `GET tipos/` — `produtos.view_tipoproduto`
Query: `busca` (nome), `ordenar` (`nome|criado_em`).
`{"results": [{"id": 1, "nome": "Celular", "numero_serial": true, "assistencia": false}], "...": "..."}`

### `GET tipos/{id}/` — `produtos.view_tipoproduto`
### `POST tipos/` — `produtos.add_tipoproduto` · `PATCH tipos/{id}/` — `produtos.change_tipoproduto`
`{"nome": "Fone", "numero_serial": false, "assistencia": false}`. Mudar `assistencia` exige
`assistencia.view_assistencia` (como a tela); sem ela → 400 `campos.assistencia`. DELETE → 405.

---

## Marcas

### `GET marcas/` — `produtos.view_marca`
Query: `ativo` (`sim|nao|todos`, padrão `sim`), `busca` (nome), `ordenar` (`nome|criado_em`).
```json
{"results": [{"id": 2, "nome": "Samsung", "cor": "#1428a0", "icone": "bx bx-mobile",
  "icone_nome": "Celular (Padrão/Samsung)", "ativo": true,
  "lojas_permitidas": [{"id": 3, "nome": "Loja Centro"}], "total_produtos": 14, "total_parcelamentos": 5}]}
```
`lojas_permitidas` mostra só as lojas do escopo de quem consulta; lista vazia = visível para todas as lojas.

### `GET marcas/{id}/` — `produtos.view_marca`
### `GET marcas/icones/` — `view_marca`, `add_marca` ou `change_marca`
`[{"valor": "bi bi-apple", "rotulo": "Apple"}, ...]` (opções do select de ícone).

### `POST marcas/` — `produtos.add_marca` · `PATCH marcas/{id}/` — `produtos.change_marca`
`{"nome": "Xiaomi", "cor": "#ff6900", "icone": "bx bx-mobile-alt", "lojas_permitidas": [3, 4]}`
- `cor`: hexadecimal (`#rgb` a `#rrggbbaa`) ou nome de cor; `icone`: um dos valores de `icones/`.
- `lojas_permitidas`: só lojas do seu escopo (senão 400 `campos.lojas_permitidas`). Na edição, as lojas atuais
  **fora** do seu escopo são preservadas (você não as vê nem as remove). Acesso global substitui a lista inteira.
- A situação muda só por ativar/desativar. Resposta 201/200 = item da lista.

### `POST marcas/{id}/ativar/` · `POST marcas/{id}/desativar/` — `produtos.change_marca`
Corpo opcional `{"motivo": "..."}`. Auditado (`marca_ativada`/`marca_desativada`). Idempotente.

---

## Parcelamentos (exclusão definitiva)

### `GET parcelamentos/` — `produtos.view_parcelamento`
Query: `busca` (nome da marca ou nº de vezes), `marca` (id), `ordenar`
(`marca|qtd_vezes|porcentagem_juros|porcentagem_desconto`; padrão marca e nº de vezes).
`{"results": [{"id": 9, "marca": {"id": 2, "nome": "Samsung", "cor": "...", "icone": "..."}, "qtd_vezes": 10,
  "porcentagem_juros": "50.00", "porcentagem_desconto": "0.00"}]}`

### `GET parcelamentos/{id}/` — `produtos.view_parcelamento`
### `POST parcelamentos/` — `produtos.add_parcelamento` · `PATCH parcelamentos/{id}/` — `produtos.change_parcelamento`
`{"marca": 2, "qtd_vezes": 12, "porcentagem_juros": "60.00", "porcentagem_desconto": "5.00"}`
- `qtd_vezes` 1–120; `porcentagem_juros` ≥ 0; `porcentagem_desconto` 0–100; `marca` visível ou `null`.
- Unicidade (marca, qtd_vezes) → 400 com `mensagem` = `"Já existe um parcelamento de 4x cadastrado para a marca Samsung."`
  e o mesmo texto em `campos.qtd_vezes`.
- Auditado (`parcelamento_criado`/`parcelamento_alterado`, com antes/depois).

### `DELETE parcelamentos/{id}/` — `produtos.delete_parcelamento`
204. Auditado (`parcelamento_excluido`, com o retrato do registro).
