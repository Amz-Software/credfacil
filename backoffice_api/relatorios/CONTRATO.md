# Contrato — módulo `relatorios` (`/api/bo/v1/relatorios/`)

Sessão do backoffice + CSRF (núcleo). Erros no contrato `{"erro": {"codigo", "mensagem", "campos"}}`. Só `GET`.
`X-Loja: <id>|todas` opcional (id fora do escopo → 403). Filtro `lojas` só aceita lojas do escopo do relatório (fora dele ou inexistente → 400 `campos.lojas`); vazio = todas as lojas do escopo.
Listas na query string repetem o parâmetro: `?lojas=1&lojas=2&status=pago&status=atrasado`. Booleanos: `true`/`false` (ausente = não filtra). Datas: `AAAA-MM-DD`; a data final é inclusiva; `data_inicial > data_final` → 400 `campos.data_final`.
Valores monetários: string decimal. Toda geração (prévia, PDF, Excel) grava auditoria `relatorio_gerado` com `dados = {"relatorio", "formato": "previa|pdf|excel", "filtros": {...}, "registros": n}`.

## Relatórios

| id | Permissão | Lojas além das do usuário | Formatos | Filtros |
|---|---|---|---|---|
| `vendas` | `vendas.can_generate_report_sale` | `vendas.can_view_all_stores` | prévia, pdf | `data_inicial`, `data_final` (data da venda), `lojas`, `produtos`, `vendedores`, `analise_serasa` (`true`=Positiva/`false`=Negativa), `parcelas`, `analise_online` |
| `solicitacoes` | `vendas.can_generate_report_sale` | `vendas.can_view_all_stores` | prévia, pdf | os de vendas (data = criação do cliente) + `status_solicitacao` (`EA`,`A`,`R`,`C`), `venda_realizada` |
| `contas_a_receber` | `vendas.can_genarate_report_payments` | `vendas.can_view_all_payments` | prévia, pdf | **`data_inicial`, `data_final`, `status` obrigatórios** (`pendente`, `pago`, `atrasado`, `desativado`, `bloqueado`, `sem_contato`, `mais_prazo`, `quitado`, `lembrete`, `flag_atrasado`, `sem_conexao`, `roubo`, `devolucao`, `todos`), `lojas`, `status_pagamento` |
| `situacoes` | `vendas.can_genarate_report_payments` | `vendas.can_view_all_payments` | prévia, pdf | `data_inicial`+`data_final` (criação da venda; só aplica com os dois), `lojas`, `situacoes` (E lógico: `lembrete`, `bo`, `flag_atrasado`, `sem_conexao`, `roubo`, `bloqueado`, `desativado`, `devolucao`, `sem_contato`, `mais_prazo`), `status_pagamento` |
| `parcelas` | `vendas.can_genarate_report_payments` | `vendas.can_view_all_payments` | prévia, pdf, excel | `lojas`, `status` (`todos`, `atrasado`, `a_vencer`, `quitado`), `data_inicial`/`data_final` (vencimento), `busca` (nome ou CPF) |

Os filtros e regras são os dos formulários/folhas atuais (o catálogo traz as opções exatas). Particularidades mantidas: em `contas_a_receber`, só o status `pago` lista **uma linha por parcela paga** no período (`totais.modo = "parcelas"`); nos demais, uma linha por pagamento (`modo = "pagamentos"`) com filtro de data por status, como a folha atual.

---

## GET `catalogo/`
**Permissão:** qualquer uma das duas permissões de relatório. Lista só os relatórios que o usuário pode gerar; opções de `lojas` e `vendedores` já vêm restritas ao escopo.
```json
[
  {
    "id": "vendas", "titulo": "Relatório de vendas", "descricao": "...",
    "formatos": ["previa", "pdf"],
    "filtros": [
      {"nome": "data_inicial", "rotulo": "Data inicial", "tipo": "data", "obrigatorio": false, "multiplo": false, "opcoes": null},
      {"nome": "lojas", "rotulo": "Lojas", "tipo": "selecao", "obrigatorio": false, "multiplo": true, "opcoes": [{"valor": 1, "rotulo": "Loja Alfa"}]},
      {"nome": "analise_online", "rotulo": "Análise online", "tipo": "booleano", "obrigatorio": false, "multiplo": false, "opcoes": [{"valor": true, "rotulo": "Sim"}, {"valor": false, "rotulo": "Não"}]},
      {"nome": "status", "rotulo": "Status", "tipo": "selecao", "obrigatorio": false, "multiplo": false, "opcoes": [...], "padrao": "todos"}
    ],
    "enderecos": {"previa": "/api/bo/v1/relatorios/vendas/previa/", "pdf": "/api/bo/v1/relatorios/vendas/pdf/"}
  }
]
```
`tipo`: `data` | `selecao` | `booleano` | `texto`. `enderecos.excel` só no relatório `parcelas`.

---

## GET `<id>/previa/`
**Permissão:** a do relatório. Parâmetros: filtros do relatório + `page`, `page_size` (máx. 100, padrão 25). Ordem fixa (data e id).
Resposta: paginação padrão + `totais` do filtro inteiro + `filtros` aplicados.
```json
{
  "count": 2, "page": 1, "page_size": 25, "total_pages": 1,
  "results": [ ...linhas... ],
  "totais": { ... },
  "filtros": {"data_inicial": "2026-01-01", "lojas": [1]}
}
```

Linhas e totais por relatório:
- **vendas** — linha: `id, loja, cliente, data_venda, vendedor, parcelas, produtos[], status_solicitacao, status_solicitacao_rotulo, segunda_compra, restricao_serasa, consulta_serasa ("Positiva"/"Negativa"), analise_online, tipo ("Online"/"Presencial"), valor_entrada, valor_repasse, valor_total, valor_juros, pagamento_bloqueado` (linha em vermelho na folha). Totais: `total_vendas, total_entrada, total_repasse, total_valor, total_juros`.
- **solicitacoes** — linha: `id (cliente), analise_id, loja, data_solicitacao, vendedor, status_solicitacao, status_solicitacao_rotulo, parcelas, produto, restricao_serasa, consulta_serasa, analise_online, tipo, venda_gerada, valor_entrada, valor_repasse, valor_total, valor_juros` (valores da venda da análise; 0 sem venda). Totais: `total_solicitacoes, total_entrada, total_repasse, total_valor, total_juros` (somam todas as vendas dos clientes, como a folha).
- **contas_a_receber** — linha: `pagamento_id, parcela_id (modo parcelas), loja, data_venda, cliente, produto, imei, situacoes[] ("ATRASADO", "A VENCER", "COBRANÇA"... ou "ATIVO"), contatos[], valor_atrasado, primeiro_vencimento, valor_pago, ultimo_pagamento, proxima_parcela, valor_a_vencer, proximo_vencimento, valor_total, parcelas_totais, parcelas_pagas, valor_quitado` (no modo parcelas só `valor_pago`/`ultimo_pagamento` vêm preenchidos; o resto `null`). Totais: `modo, quantidade, total_atrasado, total_pago, total_a_vencer, total_proximo_vencimento, total, total_quitado`.
- **situacoes** — linha: `pagamento_id, loja, data_venda, cliente, lembrete, contatos[], imei, situacoes[] ("BO", "Cobrança"...), status_pagamento[], analista_ultimo_registro, ultimo_contato {data, observacao} | null`. Totais: `quantidade`.
- **parcelas** — linha: `pagamento_id, loja, cliente, aparelho, parcelas[{numero, valor, vencimento, situacao: "pago"|"atrasado"|"a_vencer"}], total, total_pago, total_atrasado, total_a_vencer`. Totais: `quantidade, maximo_parcelas, total, total_pago, total_atrasado, total_a_vencer`.

Contém dados pessoais (nome, telefones): não guardar em cache no navegador.

---

## GET `<id>/pdf/`
**Permissão:** a do relatório. Mesmos filtros (sem paginação). PDF gerado no servidor (WeasyPrint, A4 paisagem, base `components/report_base.html`), mesmas colunas da folha atual; `parcelas` sai na mesma grade colorida da planilha.
Resposta `application/pdf`, `Content-Disposition: attachment; filename="relatorio_<id>_AAAAMMDD_HHMMSS.pdf"`, `Cache-Control: no-store`.
Limite: mais de **3000** registros → 422 `regra_de_negocio` ("Refine os filtros"). Erros sempre em JSON.

## GET `parcelas/excel/`
**Permissão:** `vendas.can_genarate_report_payments`. Filtros do relatório `parcelas`. Mesma planilha colorida atual (`.xlsx`, aba "Parcelamento"), sem limite de linhas.
Resposta `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `attachment; filename="relatorio_parcelas_AAAAMMDD_HHMMSS.xlsx"`.

## Códigos de erro
400 `validacao` (filtros; `campos` por filtro) · 401 `nao_autenticado` · 403 `proibido` (permissão ou `X-Loja` fora do escopo) · 422 `regra_de_negocio` (PDF grande demais) · 429 `limite_excedido`.
