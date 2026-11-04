# dashboard-clientes-quitados Specification

## Purpose

Define a exibição consistente da quantidade de clientes que concluíram o pagamento de financiamentos no dashboard de gráficos e no relatório PDF.

## Requirements

### Requirement: Exibir clientes com financiamento quitado
O dashboard de gráficos e seu relatório PDF MUST apresentar a quantidade de clientes únicos com financiamento IPX cujas parcelas estejam todas pagas, respeitando loja e período selecionados.

#### Scenario: Resumo geral do dashboard
- **QUANDO** o usuário abrir o dashboard com filtros de loja e período
- **ENTÃO** o resumo geral exibirá a quantidade de clientes únicos que possuem financiamento IPX quitado dentro do escopo filtrado

#### Scenario: Resumo geral do PDF
- **QUANDO** o usuário gerar o relatório PDF com os filtros de loja e período
- **ENTÃO** o resumo geral do PDF exibirá a mesma métrica calculada para o escopo solicitado

#### Scenario: Lista nominal de clientes no PDF
- **QUANDO** o relatório PDF incluir clientes com financiamento quitado no período
- **ENTÃO** apresentará o nome de cada cliente uma única vez e as lojas associadas aos financiamentos quitados incluídos no relatório

#### Scenario: Detalhamento por loja no PDF
- **QUANDO** o relatório PDF incluir mais de uma loja
- **ENTÃO** cada loja apresentará sua contagem de clientes únicos com financiamento IPX quitado
- **E** o total geral contará cada cliente apenas uma vez, ainda que tenha mais de um financiamento quitado

#### Scenario: Cliente com pagamento parcial ou não IPX
- **QUANDO** um cliente possuir financiamento IPX com ao menos uma parcela não paga ou possuir somente pagamentos de outros tipos
- **ENTÃO** esse financiamento não será considerado quitado para a métrica

#### Scenario: Financiamento concluído por diferentes origens de venda
- **QUANDO** um financiamento IPX estiver quitado, independentemente de a venda ter sido manual ou originada por análise de crédito
- **ENTÃO** o cliente será incluído na contagem conforme loja e período filtrados
