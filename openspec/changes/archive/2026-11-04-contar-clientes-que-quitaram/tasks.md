# Tarefas

## 1. Cálculo da métrica

- [x] 1.1 Implementar cálculo compartilhado de clientes distintos com financiamento IPX quitado, respeitando loja e período; conferir que a consulta exclui pagamentos parciais e conta clientes distintos com todas as parcelas pagas.
- [x] 1.2 Integrar o cálculo ao contexto do dashboard e do PDF; conferir que ambos usam os IDs de pagamentos IPX com parcelas no período e deduplicam clientes no total geral.

## 2. Apresentação no dashboard e no PDF

- [x] 2.1 Adicionar o indicador de clientes quitados ao resumo geral de `vendas/templates/dash/index.html`; conferir que o template renderiza `0` quando o contexto não fornece clientes quitados.
- [x] 2.2 Adicionar o indicador ao resumo geral do PDF, a contagem por loja e a lista nominal de clientes com suas lojas em `vendas/templates/dash/relatorio_pdf.html`; conferir que o template apresenta cliente/loja e estado vazio.

## 3. Verificação integrada

- [x] 3.1 Revisar os filtros sem data, por período e por loja nos dois cálculos e confirmar pela consulta compartilhada a deduplicação por cliente, incluindo múltiplos financiamentos e ambas as origens de venda; `manage.py check` sem erros.
