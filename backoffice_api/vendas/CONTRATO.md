# Contrato — módulo vendas (`/api/bo/v1/vendas/`)

Regras gerais (núcleo): sessão do backoffice + CSRF (`X-CSRFToken`), escopo de loja pelo
cabeçalho `X-Loja: <id>|todas`, erros no formato
`{"erro": {"codigo", "mensagem", "campos"}}`, listas paginadas
`{count, page, page_size, total_pages, results}` (`?page=`, `?page_size=` ≤ 100).

- Venda de outra loja (fora do escopo) → **404**. `X-Loja` fora do escopo → **403**.
- Método não suportado (ex.: `GET` numa ação, `PUT`/`DELETE` na venda) → **405** `metodo_nao_permitido`.
- Erros de campos aninhados usam chave achatada: `"itens.0.produto"`, `"pagamentos.1.parcelas"`.
- `ErroDeNegocio` → **422** `regra_de_negocio` (ou 403 `proibido` quando a regra é de acesso).
- Valores monetários são strings decimais (`"1200.00"`); datas ISO 8601.
- CPF: mascarado (`***.456.789-**`) em listas; completo só no detalhe.
- Escopo global de vendas: `vendas.can_view_all_sales` (ou `vendas.can_view_all_stores`/superusuário).

---

## GET `vendas/` — lista
Permissão: `vendas.view_venda`.

Parâmetros: `busca` (número, nome ou CPF do cliente — 3+ dígitos —, IMEI — 4+ dígitos),
`cliente` (nome, contém), `numero` (id), `loja` (id; **só aplicado** para quem tem escopo
global, senão é ignorado — use `X-Loja`), `canceladas` (`false` padrão = só ativas, `true` = só
canceladas, `todas`), `trocadas` (`true|false`), `origem` (`manual|analise`), `data_inicio`,
`data_fim` (AAAA-MM-DD, sobre a data da venda), `ordenar` (`numero`, `data_venda`, `cliente`,
`loja`, `vendedor`, `total`, `modificado_em`; `-` para decrescente; padrão `-data_venda`).

```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [{
  "id": 12, "numero": 12, "data_venda": "2026-11-20T10:31:00-03:00",
  "cliente": {"id": 5, "nome": "Maria Souza"}, "cpf_mascarado": "***.456.789-**",
  "loja": {"id": 1, "nome": "Loja A"}, "vendedor": {"id": 3, "nome": "João"},
  "total": "1200.00", "situacao": "ativa", "origem": "analise", "tem_iphone": false,
  "is_deleted": false, "is_trocado": false, "documentos_completos": false,
  "status_contrato": "AGUARDANDO_ASSINATURA", "modificado_por": {"id": 3, "nome": "João"},
  "modificado_em": "2026-11-20T10:31:00-03:00"}]}
```
`situacao`: `ativa | cancelada | trocada`. Erros: 400 (`ordenar`, datas, `numero`, `trocadas`, `origem` inválidos).

## GET `vendas/{id}/` — detalhe
Permissão: `vendas.view_venda`. Campos da lista + :

```json
{
  "cliente": {"id": 5, "nome": "Maria Souza", "cpf": "12345678901", "rg": "1234", "nascimento": "1990-01-01",
              "telefone": "91999999999", "telefone_secundario": "", "email": null, "cep": "66000000",
              "endereco": "Rua A", "bairro": "Centro", "cidade": "Belém"},
  "observacao": "...", "repasse_logista": "1000.00", "valor_total_pagamentos": "1400.00",
  "valor_entrada": "200.00", "caixa": null, "criado_por": {"id": 3, "nome": "João"}, "criado_em": "...",
  "itens": [{"id": 30, "produto": {"id": 2, "nome": "Galaxy A15", "codigo": 7, "is_iphone": false},
             "imei": "3500...", "quantidade": 1, "valor_unitario": "1200.00", "valor_desconto": "0.00",
             "valor_total": "1200.00"}],
  "pagamentos": [{"id": 40, "tipo_pagamento": {"id": 2, "nome": "IPX", "carne": true, "parcelas": true,
                  "caixa": false, "financeira": false},
                  "valor": "1200.00", "parcelas": 10, "valor_parcela": "120.00", "data_primeira_parcela": "2026-12-10",
                  "porcentagem_desconto": "5.00", "bloqueado": false, "desativado": false, "devolucao": false,
                  "quitado": false,
                  "resumo": {"total": 10, "pagas": 1, "atrasadas": 0, "a_vencer": 9, "valor_pago": "120.00",
                             "valor_atrasado": "0.00", "valor_a_vencer": "1080.00", "proximo_vencimento": "2027-01-10"},
                  "parcelas_lista": [{"id": 1, "numero_parcela": 1, "valor": "120.00", "desconto": "0.00",
                                      "valor_pago": "120.00", "valor_restante": "0.00", "data_vencimento": "2026-12-10",
                                      "data_pagamento": "2026-12-09", "pago": true, "pagamento_efetuado": true,
                                      "situacao": "paga"}]}],
  "analise_origem": {"id": 9, "status": "A", "status_display": "Aprovado", "data_analise": "...",
                     "data_aprovacao": "...", "aprovado_por": {"id": 4, "nome": "Ana"},
                     "produto": {"id": 2, "nome": "Galaxy A15"}, "numero_parcelas": "10", "data_pagamento": "10",
                     "entrada_informada": null, "analise_online": false, "segunda_compra": false},
  "documentos": [{"campo": "documento_assinado", "rotulo": "Documento assinado", "presente": true,
                  "nome_arquivo": "documento_assinado_ab12.pdf",
                  "url": "/api/bo/v1/vendas/12/arquivos/documento_assinado/"}],
  "impressos": {"nota": "/api/bo/v1/vendas/12/nota.pdf", "contrato": "/api/bo/v1/vendas/12/contrato.pdf",
                "carne": "/api/bo/v1/vendas/12/carne.pdf?tipo=carne",
                "promissoria": "/api/bo/v1/vendas/12/carne.pdf?tipo=promissoria"},
  "acoes": {"editar": true, "edicao_especial": false, "trocar_produto": true, "cancelar": false,
            "enviar_documentos": true},
  "historico": [{"origem": "acao", "data": "...", "usuario": "ana", "tipo": "venda_produto_trocado",
                 "descricao": "", "motivo": "Defeito", "campos": []},
                {"origem": "alteracao", "data": "...", "usuario": "Ana", "tipo": "alteracao", "descricao": "",
                 "motivo": "", "campos": [{"campo": "is_trocado", "de": false, "para": true}]}]
}
```
`analise_origem` é `null` em venda manual; `carne`/`promissoria` são `null` sem pagamento em carnê.
`acoes` é só conforto de interface (o servidor confere de novo). `historico`: até 50 eventos
(simple_history + auditoria com motivo), do mais recente ao mais antigo. Situação da parcela:
`paga | atrasada | a_vencer` (pagamento em devolução não conta atrasadas/a vencer).

## PATCH `vendas/{id}/` — edição
Permissão: `vendas.change_venda`. Venda gerada por análise (“venda finalizada”) exige também
grupo ANALISTA/ADMINISTRADOR **ou** `vendas.can_edit_finished_sale` (senão 403). Venda cancelada → 422.

Todos os campos são opcionais (envie ao menos um). Itens/pagamentos não enviados ficam como estão.
```json
{
  "cliente": 5, "vendedor": 3, "observacao": "texto",
  "itens": [
    {"id": 30, "imei": "359...", "quantidade": 1, "valor_unitario": "1200.00", "valor_desconto": "50.00"},
    {"produto": 8, "quantidade": 1, "valor_unitario": "300.00", "valor_desconto": "0.00", "imei": "351..."},
    {"id": 31, "remover": true}
  ],
  "pagamentos": [
    {"id": 40, "valor": "1300.00", "parcelas": 10, "data_primeira_parcela": "2026-12-10", "porcentagem_desconto": "5.00", "tipo_pagamento": 2},
    {"tipo_pagamento": 1, "valor": "100.00", "parcelas": 1, "data_primeira_parcela": "2026-11-23"},
    {"id": 41, "remover": true}
  ]
}
```
- Item novo exige `produto`, `quantidade`, `valor_unitario`; o produto precisa estar liberado
  para a loja da venda. Trocar o produto de um item existente → 400 (use `trocar-produto`).
- A venda precisa manter ao menos um item.
- Alterar `valor`, `parcelas` ou `data_primeira_parcela` recria as parcelas do pagamento
  (mesmo dia nos meses seguintes). Se o pagamento tem parcela paga/informada → **422** (o mesmo
  vale para remover o pagamento). Mudar só `tipo_pagamento`/`porcentagem_desconto` não recria.
- `cliente` precisa estar no escopo de lojas; `vendedor` precisa estar ativo.
- Nada é recalculado (repasse, juros, entrada): os valores enviados são gravados.

Resposta: 200 com o **detalhe** recarregado. Auditoria `venda_editada` (resumo antes/depois).
Erros: 400 (`itens.N.campo`, `pagamentos.N.campo`, `cliente`, `vendedor`), 403, 404, 422.

## POST `vendas/{id}/edicao-especial/`
Permissão: `vendas.can_edit_imei_valores_venda`. Motivo obrigatório (≥ 5 caracteres). Venda cancelada → 422.
```json
{"motivo": "Cliente pediu outro aparelho",
 "itens": [{"id": 30, "produto": 8, "imei": "357..."}],
 "pagamentos": [{"id": 40, "parcelas": 12}]}
```
`parcelas` ∈ {4, 6, 8, 10, 12, 14}; a ENTRADA não é parcelada (400). Produto precisa estar
liberado para a loja. **Valores monetários são preservados** (como a API atual): mudar as
parcelas recria as parcelas com o mesmo valor total. Pagamento com parcela paga → 422.
Resposta: detalhe. Auditoria `venda_edicao_especial` com motivo.

## GET `vendas/{id}/opcoes-edicao/`
Permissão: `vendas.change_venda` ou `vendas.can_edit_imei_valores_venda`. Opções dos formulários
de edição/edição especial da SPA (o servidor valida de novo cada escolha).
```json
{"tipos_pagamento": [{"id": 2, "nome": "IPX", "carne": true, "parcelas": true, "caixa": false, "financeira": false}],
 "vendedores": [{"id": 3, "nome": "João"}],
 "produtos": [{"id": 2, "nome": "Galaxy A15", "codigo": 7, "is_iphone": false, "valor": "1200.00", "serializado": true}],
 "parcelas_edicao_especial": [4, 6, 8, 10, 12, 14],
 "limite_desconto_percentual": 15}
```
`vendedores`: usuários ativos da loja da venda (usuários e gerentes) + o vendedor atual.
`produtos`: liberados para a loja da venda (`produtos_permitidos_qs`, sem exigir estoque);
`serializado` = tipo com número de série (IMEI obrigatório, quantidade 1).
`limite_desconto_percentual`: acima dele (desconto ÷ subtotal do item) a tela pede
`autorizacao-gerente/` antes de salvar (regra de interface, como `static/js/venda-edit.js`).

## GET `vendas/clientes/?busca=`
Permissão: `vendas.change_venda`. Paginado; clientes no escopo de lojas, por nome (contém) ou
CPF (3+ dígitos). `{"results": [{"id": 5, "nome": "Maria Souza", "cpf_mascarado": "***.456.789-**"}]}`.

## GET `vendas/{id}/opcoes-troca/`
Permissão: `vendas.change_venda`.
```json
{"itens": [{"id": 30, "produto": {...}, "imei": "350...", ...}],
 "produtos_disponiveis": [{"id": 8, "nome": "Galaxy A25"}]}
```
Produtos com estoque disponível (`Estoque.quantidade_disponivel > 0`) na loja da venda.

## GET `vendas/imeis-disponiveis/?produto=<id>[&venda=<id>][&busca=]`
Permissão: `vendas.change_venda` ou `vendas.can_edit_imei_valores_venda`. Paginado.
IMEIs do produto não vendidos, não cancelados e **que não estão em outra venda ativa**, no
escopo de lojas (todas com `estoque.can_view_all_imei`). `venda` restringe à loja da venda.
```json
{"count": 1, "...": "...", "results": [{"id": 77, "imei": "3566...", "produto": {"id": 8, "nome": "Galaxy A25"},
  "loja": {"id": 1, "nome": "Loja A"}}]}
```
Erros: 400 sem `produto`; 400 `venda` não encontrada.

## POST `vendas/{id}/trocar-produto/`
Permissão: `vendas.change_venda`.
```json
{"produto_atual": 30, "novo_produto": 8, "imei": 77, "motivo": "Defeito de fábrica"}
```
`produto_atual` = id do item; `imei` = id do IMEI (de `imeis-disponiveis`), que precisa ser do
novo produto. Marca a venda como trocada e acrescenta o registro na observação (mesmo texto da
tela). Estoque/IMEI antigo não são alterados. Resposta: detalhe. Auditoria `venda_produto_trocado`.
Erros: 400 (`produto_atual`, `novo_produto`, `imei`, `motivo`), 422 venda cancelada.

## POST `vendas/{id}/cancelar/`
Permissão: `vendas.delete_venda`. `{"motivo": "Cliente desistiu"}`. Soft delete
(`is_deleted`); o IMEI **não** é restaurado. Já cancelada → 422. Resposta: detalhe.
Auditoria `venda_cancelada`.

## POST `vendas/{id}/documentos/` (multipart)
Permissão: `vendas.change_venda`. Qualquer subconjunto de `documento_assinado` (PDF, JPG, PNG,
WEBP), `foto_cliente` e `imagem_imei` (JPG, PNG, WEBP; `imagem_imei` só em venda com iPhone).
Tipo conferido pelo conteúdo; máximo 10 MB; nome do arquivo gerado no servidor (imagens podem
virar WEBP). Resposta: detalhe. Auditoria `venda_documentos_enviados`.
Erros: 400 (campo do arquivo; nenhum arquivo), 422 venda cancelada.

## GET `vendas/{id}/arquivos/<campo>/`
Permissão: `vendas.view_venda`. `campo` ∈ `documento_assinado | foto_cliente | imagem_imei`.
Entrega o arquivo (`inline` para PDF/imagem, `attachment` para outros tipos antigos;
`X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`). Sem arquivo → 404.
Auditoria `venda_documento_acessado`. A SPA deve baixar com `fetch` (credenciais) e abrir como blob.

## PDFs (WeasyPrint)
Permissão: `vendas.view_venda`. Respondem `application/pdf` (`inline`); erros em JSON.
Auditoria `venda_pdf_gerado`.
- `GET vendas/{id}/nota.pdf` — nota de venda (loja, cliente, itens, pagamentos, garantia).
- `GET vendas/{id}/carne.pdf?tipo=carne|promissoria` — uma folha por parcela do pagamento em
  carnê, valor = valor do pagamento / parcelas, QR Code PIX da loja marcada como CredFacil.
  400 `tipo` inválido; 422 sem pagamento em carnê ou sem loja CredFacil com chave PIX.
- `GET vendas/{id}/contrato.pdf` — contrato de locação (via do cliente e via do lojista) com o
  texto Editor.js **da loja da venda** convertido e sanitizado no servidor.

## GET `vendas/produtos-vendidos/`
Permissão: `vendas.view_produtovenda`; todas as lojas com `vendas.can_view_all_products_sold`.
Parâmetros: `nome` (produto), `cpf`, `imei`, `loja` (só com a permissão global), `canceladas`
(`true|false`; sem filtro = todas), `data_inicio`, `data_fim`, `ordenar` (`data_venda`,
`produto`, `cliente`, `loja`, `valor`, `venda`; padrão `-data_venda`).
```json
{"results": [{"id": 30, "venda": {"id": 12, "data_venda": "...", "situacao": "ativa"},
  "produto": {"id": 2, "nome": "Galaxy A15", "codigo": 7, "is_iphone": false}, "imei": "350...",
  "quantidade": 1, "valor_unitario": "1200.00", "valor_desconto": "0.00", "valor_total": "1200.00",
  "cliente": {"id": 5, "nome": "Maria"}, "cpf_mascarado": "***.456.789-**",
  "loja": {"id": 1, "nome": "Loja A"}, "vendedor": "João"}]}
```

## POST `vendas/autorizacao-gerente/`
Permissão: `vendas.change_venda` ou `vendas.add_venda`. Limite de tentativas: escopo `login`
(e bloqueio por tentativas do django-axes para o usuário informado). Não cria sessão.
```json
{"usuario": "gerente", "senha": "...", "venda": 12}
```
Loja: a da `venda`; senão `loja` (id no escopo, senão 403); senão a única loja do escopo (ou
`X-Loja`); sem como decidir → 400 `loja`. 200:
```json
{"autorizado": true, "gerente": {"id": 7, "nome": "Carla"}, "loja": {"id": 1, "nome": "Loja A"}}
```
403 `proibido` com mensagem “usuário ou senha incorretos” ou “não é gerente desta loja”;
429 `limite_excedido` quando bloqueado. Sucesso e falha auditados
(`autorizacao_gerente_concedida` / `autorizacao_gerente_negada`, com o motivo).

## GET `vendas/busca/?termo=` — provedor da busca global
Permissão: `vendas.view_venda`. `termo` com 2+ caracteres (ou só dígitos). Até 8 resultados
(número exato primeiro, depois os mais recentes), no escopo de lojas.
```json
[{"tipo": "venda", "id": 12, "titulo": "Venda #12",
  "descricao": "Maria Souza · ***.456.789-** · Loja A · 20/11/2026", "situacao": "ativa", "rota": "/vendas/12"}]
```
