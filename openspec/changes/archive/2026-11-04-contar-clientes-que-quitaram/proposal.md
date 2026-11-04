# Proposta: Contar clientes que quitaram

## Por quê

O resumo geral do dashboard de gráficos apresenta vendas, parcelas pagas e clientes inadimplentes, mas não mostra quantos clientes concluíram o pagamento de seus financiamentos. Incluir essa métrica também no relatório PDF permite comparar o indicador entre dashboard e relatório exportado.

## O que muda

- Adicionar ao resumo geral do dashboard a quantidade de clientes únicos com financiamento IPX quitado.
- Incluir o mesmo indicador no resumo geral do PDF e uma contagem por loja, para que o relatório mantenha o detalhamento já oferecido às demais métricas.
- Incluir no PDF uma lista nominal dos clientes quitados, indicando as lojas em que cada cliente possui financiamento quitado no período.
- Considerar quitado o financiamento IPX cujas parcelas estejam todas pagas; contar o cliente uma única vez por loja, mesmo que possua mais de um financiamento quitado.
- Respeitar a loja selecionada e o período aplicado aos dados do dashboard/relatório. A métrica considera os pagamentos no escopo filtrado e não altera contratos REST, permissões ou sessões.
- Abranger financiamentos de vendas manuais e de vendas originadas por análise de crédito, sem alterar os respectivos fluxos de criação.

## Capacidades

### Novas capacidades
- `dashboard-clientes-quitados`: Exibir a contagem de clientes com financiamento quitado no dashboard de gráficos e no relatório PDF.

### Capacidades modificadas
- Nenhuma.

## Impacto

- Backend: cálculo e contexto da `GraficoTemplateView` e do `DashboardReportPDFView`, em `vendas/views.py`.
- Interface web: resumo geral em `vendas/templates/dash/index.html`.
- PDF: resumo geral e tabela de lojas em `vendas/templates/dash/relatorio_pdf.html`.
- API REST, WebSocket, payloads, sessões e permissões: sem mudanças previstas.
- Sem mudanças em modelos, banco de dados ou dependências.
