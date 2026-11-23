# Contrato — módulo `painel` (`/api/bo/v1/painel/`)

Sessão do backoffice + CSRF (núcleo). Erros no contrato `{"erro": {"codigo", "mensagem", "campos"}}`.
Cabeçalho `X-Loja: <id>|todas` opcional: id fora do escopo → 403 `proibido`; valor inválido → 400 `validacao`.
Sem `X-Loja` (ou `todas` sem permissão global) vale o escopo inteiro do usuário.
Valores monetários: string decimal (`"1234.50"`). Séries de gráfico: números (`float`). Datas: `AAAA-MM-DD`.
Só `GET`; outros métodos → 403/405.

---

## GET `resumo/`
Painel inicial por papel. **Permissão:** basta acesso ao backoffice; cada bloco vem `null` se o usuário não tiver a permissão dele.

| Bloco | Permissão | Escopo de lojas |
|---|---|---|
| `kpis` | `vendas.can_view_your_dashboard` | escopo do usuário / `X-Loja` (soma as lojas quando há mais de uma) |
| `analise` | `vendas.view_cliente` | idem; com `vendas.view_all_analise_credito` e sem `X-Loja`, todas |
| `financeiro` | `vendas.view_pagamento` | idem; com `vendas.can_view_all_payments` e sem `X-Loja`, todas |
| `atalhos` | cada atalho pela sua permissão | — |

Regras: `kpis` = mesma regra da tela inicial (`vendas.services.kpis.resumo_carteira_loja`: 3 primeiras parcelas IPX ativas de cada venda; `total_vendas` conta também vendas canceladas, como hoje). `analise.tempo_*` = minutos desde a criação das solicitações em análise (`EA`). `financeiro` = parcelas em aberto com vencimento passado de pagamentos parcelados (fora do caixa), de vendas ativas e sem devolução; `valor_em_atraso` = Σ(valor − desconto − valor pago).

```json
{
  "loja": {"id": 3, "nome": "Loja Centro"},
  "quantidade_lojas": 1,
  "kpis": {
    "parcelas_consideradas_por_venda": 3,
    "total_vendas": 120, "total_parcelas": 340, "valor_total": "51000.00",
    "parcelas_pagas": 200, "valor_pago": "30000.00",
    "parcelas_vencidas": 40, "valor_vencido": "6000.00",
    "parcelas_a_vencer": 100, "valor_a_vencer": "15000.00",
    "desativados": {"total_pagamentos": 2, "parcelas_vencidas": 3, "valor_vencido": "450.00", "parcelas_a_vencer": 5, "valor_a_vencer": "750.00"},
    "grafico_balanco": {"unidade": "percentual", "rotulos": ["Pagas", "Vencidas", "Desativados"], "valores": [57.0, 11.4, 2.3]}
  },
  "analise": {
    "por_status": [{"status": "EA", "rotulo": "Em análise", "total": 4}, {"status": "A", "rotulo": "Aprovado", "total": 50}, {"status": "R", "rotulo": "Reprovado", "total": 7}, {"status": "C", "rotulo": "Cancelado", "total": 1}],
    "total": 62, "em_espera": 4, "tempo_medio_espera_minutos": 35, "maior_espera_minutos": 80
  },
  "financeiro": {"parcelas_atrasadas": 40, "valor_em_atraso": "5800.00", "pagamentos_em_atraso": 25, "clientes_inadimplentes": 24},
  "atalhos": [{"id": "fila_credito", "titulo": "Solicitações de crédito", "descricao": "..."}]
}
```
`loja` só vem preenchida quando o recorte tem uma loja. Ids de atalho: `fila_credito`, `vendas`, `contas_a_receber`, `produtos`, `relatorios`, `graficos`, `crm` (a SPA mapeia id → rota).

---

## GET `graficos/`
Dashboard de gráficos (mesmos números da tela `dash/` — `GraficoTemplateView`).
**Permissão:** `vendas.can_view_all_dashboard` (que também libera todas as lojas, como hoje).

Parâmetros: `loja` (id, dentro do escopo; senão 400 `campos.loja`), `data_inicio`, `data_fim` (AAAA-MM-DD; `data_inicio > data_fim` → 400 `campos.data_fim`).
Regras do período (iguais às da tela): parcelas IPX entram pela data do pagamento (pagas) ou do vencimento; quantidade de vendas e repasses pela data da venda; `clientes_quitados` segue a spec `dashboard-clientes-quitados`.

```json
{
  "filtros": {"loja": null, "data_inicio": "2026-01-01", "data_fim": "2026-06-30"},
  "lojas_disponiveis": [{"id": 1, "nome": "Loja Alfa"}, {"id": 2, "nome": "Loja Beta"}],
  "resumo": {
    "total_vendas": 80, "total_parcelas": 400, "valor_total_parcelas": "60000.00", "total_repasses": "52000.00",
    "parcelas_pagas": 250, "valor_pago": "37000.00", "parcelas_vencidas": 50, "valor_vencido": "7500.00",
    "parcelas_a_vencer": 100, "valor_a_vencer": "15500.00", "clientes_vencidos": 30, "clientes_quitados": 12,
    "cobranca": {"total_pagamentos": 5, "parcelas_vencidas": 6, "valor_vencido": "900.00", "parcelas_a_vencer": 10, "valor_a_vencer": "1500.00"},
    "desativados": {"total_pagamentos": 3, "parcelas_vencidas": 4, "valor_vencido": "600.00", "parcelas_a_vencer": 8, "valor_a_vencer": "1200.00"}
  },
  "repasses_por_loja": [{"loja": {"id": 1, "nome": "Loja Alfa"}, "valor": "30000.00"}],
  "por_loja": {
    "lojas": [{"id": 1, "nome": "Loja Alfa"}],
    "rotulos": ["Loja Alfa"],
    "totais": [42000.0],
    "series": [
      {"id": "pagas", "rotulo": "% Pagas", "percentuais": [61.9], "valores": [26000.0]},
      {"id": "vencidas", "rotulo": "% Vencidas", "percentuais": [11.9], "valores": [5000.0]},
      {"id": "desativados", "rotulo": "% Desativados", "percentuais": [2.4], "valores": [1000.0]},
      {"id": "cobrancas", "rotulo": "% Cobranças", "percentuais": [3.6], "valores": [1500.0]}
    ]
  },
  "por_loja_mes": null
}
```
`por_loja`: barras empilhadas em %, uma por loja (`rotulos`), `valores` em R$ de cada fatia, `totais` em R$ por loja.
`por_loja_mes` (só quando o recorte é de **uma** loja, via `loja` ou `X-Loja`): `{"rotulos": ["2026-01", ...], "series": [{"loja": {...}, "situacao": "pago|vencido|a_vencer", "rotulo": "Loja Alfa - Pago", "percentuais": [70, ...] (inteiros), "valores": [...], "totais": [...]}]}`.

---

## GET `graficos/relatorio.pdf`
PDF do dashboard (mesmo template e conteúdo do PDF atual, `dash/relatorio_pdf.html`, inclusive a lista nominal de clientes que quitaram).
**Permissão:** `vendas.can_generate_dashboard_report` (libera todas as lojas). Mesmos parâmetros de `graficos/`.
Resposta: `application/pdf`, `Content-Disposition: attachment; filename="relatorio_dashboard_AAAAMMDD_HHMMSS.pdf"`. Erros continuam em JSON (mesmo com `Accept: application/pdf`).
Auditoria: `relatorio_gerado` com `dados = {"relatorio": "painel_graficos", "formato": "pdf", "filtros": {...}, "lojas": [...], "clientes_listados": n}`.

## Códigos de erro
400 `validacao` (filtros, `X-Loja` inválido) · 401 `nao_autenticado` · 403 `proibido` (permissão ou loja fora do escopo) · 429 `limite_excedido`.
