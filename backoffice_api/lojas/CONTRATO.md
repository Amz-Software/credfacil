# Contrato — `/api/bo/v1/lojas/` (lojas, repasses e números autenticadores)

Sessão do backoffice + `X-CSRFToken` em toda mutação. Cabeçalho opcional `X-Loja: <id>|todas`.
Escopo: lojas em que o usuário é usuário/gerente (ou `user.loja`); `vendas.can_view_all_stores` ou superusuário
vê todas. Loja/objeto fora do escopo → **404**; `X-Loja` fora do escopo → 403. Método não suportado → **405**.
Erros: `{"erro": {"codigo", "mensagem", "campos"}}`. Dinheiro em string decimal; datas ISO 8601.
Os campos legados `porcentagem_desconto_{4,6,8,10}` não existem nesta API (enviá-los → 400).

---

## GET `` (lista de lojas)
Permissão: `vendas.view_loja`. Paginado. Parâmetros: `busca` (nome ou CNPJ), `repasse` = `pendente` | `sem_pendente`
(repasse registrado pendente com data ≤ hoje).
```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [
 {"id": 1, "nome": "Loja A", "cnpj": "...", "telefone": "...", "endereco": "...", "pode_vender_iphone": false,
  "credfacil": true, "repasses": {"situacao": "pendente", "atrasados": 2}}]}
```
`repasses.situacao` (calendário do mês atual): `pendente` (há data vencida sem repasse), `em_dia`, `sem_dados`.

## POST `` (criar loja)
Permissão: `vendas.add_loja`. JSON ou multipart. Auditado (`loja_criada`). Resposta 201 = detalhe da loja (abaixo, bloco `loja`).

Campos: `nome` (obrigatório), `cnpj`, `inscricao_estadual`, `endereco`, `telefone`, `meta_vendas_diaria`,
`meta_vendas_mensal`, `entrada_caixa_diaria`, `mensagem_garantia`, `chave_pix`, `codigo_aplicativo`,
`contrato` (JSON do Editor.js `{"time", "blocks": [{"type", "data"}], "version"}`; em multipart, texto JSON),
`usuarios` / `gerentes` (ids de usuários ativos), `produtos_bloqueados` (ids de produtos ativos),
`logo_loja`, `qr_code_aplicativo` (imagem PNG/JPEG/WEBP até 10 MB, conferida pelo conteúdo),
`pode_vender_iphone` (**só ADMINISTRADOR ou superusuário**; outros → 400 em `campos.pode_vender_iphone`).
`credfacil` é só leitura (como na tela). Campo desconhecido → 400 "Campo não editável".

## GET `opcoes/` (opções do formulário de loja)
Permissão: `vendas.add_loja` **ou** `vendas.change_loja`. Mesmas listas do `LojaForm` da tela Django.
```json
{"usuarios": [{"id": 3, "nome": "Ana", "email": "ana@x"}],
 "produtos": [{"id": 9, "nome": "iPhone 13", "codigo": 101}],
 "pode_editar_campos_restritos": false}
```
`usuarios`: ativos (usuários e gerentes); `produtos`: ativos (modelos bloqueáveis);
`pode_editar_campos_restritos`: ADMINISTRADOR ou superusuário (libera `pode_vender_iphone`).

## GET `{id}/` (detalhe)
Permissão: `vendas.view_loja`. Parâmetros `data_inicio`, `data_fim` (AAAA-MM-DD) recortam KPIs e calendário.
```json
{"loja": {"id": 1, "nome": "Loja A", "cnpj": null, "inscricao_estadual": null, "endereco": "...", "telefone": "...",
          "meta_vendas_diaria": "1000.00", "meta_vendas_mensal": null, "entrada_caixa_diaria": null,
          "mensagem_garantia": "...", "contrato": {"blocks": []}, "chave_pix": "...", "codigo_aplicativo": "ABC",
          "pode_vender_iphone": false, "credfacil": true,
          "usuarios": [{"id": 3, "nome": "Ana", "email": "ana@x"}], "gerentes": [],
          "produtos_bloqueados": [{"id": 9, "nome": "iPhone 13", "codigo": 101}],
          "url_logo": "/api/bo/v1/lojas/1/logo/", "url_qr_code": null, "criado_em": "...", "modificado_em": "..."},
 "periodo": {"data_inicio": null, "data_fim": null},
 "kpis": {"qtd_vendas": 12, "valor_total": "15400.00", "valor_repasse": "9800.00"},
 "calendario_repasses": {"atrasados": 1, "periodos": [
   {"data": "2026-10-16", "inicio_periodo": "2026-10-06", "fim_periodo": "2026-10-15", "qtd_vendas": 3,
    "valor_total_repasse": "2100.00", "feito": true, "parcial": false, "atrasado": false}]}}
```
`calendario_repasses` cobre o mês anterior e o atual (dias 6/16/26; períodos sem venda omitidos) e é `null`
sem `financeiro.view_repasse`. `parcial` = repasse lançado com valor menor que o devido (calculado, nada é gravado).

## PATCH `{id}/`
Permissão: `vendas.change_loja`. Mesmos campos do POST, parciais. Auditado (`loja_alterada`, antes/depois dos campos
simples e ids de usuários/gerentes/produtos). Resposta: bloco `loja`.

## GET `{id}/vendas/`
Permissão: `vendas.view_loja`. Paginação própria (`page`, `page_size`), `data_inicio`, `data_fim`.
`{"count", "page", "page_size", "total_pages", "results": [{"id", "data_venda", "cliente": {"id", "nome"}, "repasse_logista", "valor_total"}]}`
(`valor_total` = pagamentos contabilizáveis da venda).

## GET `{id}/logo/` · GET `{id}/qrcode/`
Permissão: `vendas.view_loja`. Entregam a imagem (nunca o caminho de `/mediafiles/`). 404 se não houver.

## POST `{id}/replicar-qrcode/`
Permissão: `vendas.change_loja` + grupo ADMINISTRADOR (ou superusuário). Sem corpo.
Copia QR code e código do aplicativo para todas as outras lojas. Auditado (`loja_qrcode_replicado`).
`{"lojas_alteradas": 7, "mensagem": "..."}`. 422 se a loja não tem QR code/código.

---

## Repasses

Status: `pendente`, `pago`, `cancelado` e `parcial` (legado: gravado pelas telas antigas). Transições:
`pendente|parcial → pago|cancelado`. `pago`/`cancelado` são finais (mudar status, valor ou data → 422;
`observacao` continua editável).

### GET `repasses/`
Permissão: `financeiro.view_repasse`. Paginado. Parâmetros: `loja` (id no escopo, senão 404), `status`,
`data_inicio`, `data_fim`, `ordenar` (`data` padrão `-data`, `valor`, `status`, `criado_em`).
```json
{"results": [{"id": 4, "loja": {"id": 1, "nome": "Loja A"}, "valor": "2500.00", "data": "2026-11-06",
  "status": "pendente", "status_rotulo": "Pendente", "observacao": "Quinzena", "criado_por": "Ana",
  "criado_em": "...", "atualizado_por": "Ana", "atualizado_em": "..."}], "count": 1, "page": 1, "page_size": 25, "total_pages": 1}
```

### POST `repasses/`
Permissão: `financeiro.add_repasse`. Auditado (`repasse_criado`).
`{"loja": 1, "valor": "2500.00", "data": "2026-11-06", "status": "pendente", "observacao": "..."}`
(`status` opcional: `pendente` padrão, `pago`, `cancelado`; `loja` fora do escopo → 400 em `campos.loja`). Resposta 201.

### PATCH `repasses/{id}/`
Permissão: `financeiro.change_repasse`. Campos: `valor`, `data`, `status`, `observacao`, `motivo` (opcional).
Auditado: `repasse_status_alterado` (antes/depois + motivo) e `repasse_alterado` (outros campos). Erros: 400, 404, 422.

### GET `repasses/agendados/`
Permissão: `financeiro.view_repasse`. Paginado por loja (ordem alfabética). Parâmetros: `loja`, `meses_atras` (0–6, padrão 1).
```json
{"results": [{"loja": {"id": 1, "nome": "Loja A"}, "total_atrasados": 1,
  "atrasados": [{"data": "2026-10-16", "inicio_periodo": "...", "fim_periodo": "...", "qtd_vendas": 2,
                 "valor_total_repasse": "1400.00", "feito": false, "parcial": false, "atrasado": true}],
  "proximos": [{"data": "2026-11-26", "...": "..."}]}], "count": 1, "page": 1, "page_size": 25, "total_pages": 1}
```

---

## Números autenticadores — `numeros-autenticadores/`
Permissão: grupo ANALISTA ou ADMINISTRADOR (ou superusuário). Escopo pela loja do número.

| Método | Caminho | Observação |
|---|---|---|
| GET | `numeros-autenticadores/` | paginado; `busca` (número/descrição), `ativo` (`true`/`false`) |
| POST | `numeros-autenticadores/` | `{"numero": "(91) 99999-0000", "descricao": "...", "ativo": true, "loja_id": 1}` → 201 |
| GET | `numeros-autenticadores/{id}/` | |
| PATCH | `numeros-autenticadores/{id}/` | campos parciais |
| DELETE | `numeros-autenticadores/{id}/` | exclusão definitiva, 204, auditada (`numero_autenticador_removido`) |

Item: `{"id", "numero", "descricao", "ativo", "loja": {"id", "nome"} | null, "criado_em", "modificado_em"}`.
`numero` precisa de 10 ou 11 dígitos (guardado como digitado). Sem `loja_id`: usa a loja de `X-Loja`; quem tem
acesso global e não escolheu loja grava sem loja; usuário com uma única loja usa ela; senão 400 `campos.loja_id`.
