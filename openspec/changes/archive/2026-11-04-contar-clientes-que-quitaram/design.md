# Desenho técnico

## Contexto

O dashboard em `vendas/views.py` prepara os dados da tela e o endpoint PDF possui um cálculo próprio. Ambos consideram parcelas IPX com filtros de data, e o PDF já agrega métricas por loja. O modelo de pagamentos oferece estados e anotações de quitação baseadas na relação entre parcelas pagas e parcelas totais. Ver `proposal.md` para a motivação e `specs/dashboard-clientes-quitados/spec.md` para o comportamento esperado.

## Objetivos / Fora de escopo

**Objetivos:**
- Calcular clientes quitados de forma consistente nos dois caminhos de relatório.
- Respeitar o escopo de lojas, o período selecionado e a unicidade do cliente.
- Não adicionar campos persistidos nem alterar fluxos de criação de vendas.

**Fora de escopo:**
- Alterar o significado da flag operacional `Pagamento.quitado`.
- Mudar APIs, permissões, contratos de vendas, ou cálculos financeiros existentes.

## Decisões

- Considerar um financiamento quitado quando possuir parcelas e todas elas estiverem marcadas como pagas, usando o critério de domínio existente (`todas_parcelas_pagas`) em vez da flag `Pagamento.quitado`, que pode refletir uma situação operacional distinta.
- Contar clientes distintos por loja; no resumo geral do PDF, agregar IDs distintos sobre as lojas selecionadas para evitar duplicar um cliente que tenha financiamentos em mais de uma loja.
- Apresentar no PDF uma lista geral de clientes quitados, uma linha por cliente, agregando os nomes das lojas associadas. A contagem por loja permanece no resumo e no detalhamento existentes.
- Aplicar a mesma semântica de período dos dados de parcelas já carregados em cada relatório: uma parcela entra no escopo pela data de pagamento quando paga e com data registrada; caso contrário, pela data de vencimento. Um financiamento só é candidato se tiver parcelas no período, mas sua quitação é verificada considerando o conjunto integral de parcelas do financiamento.
- Centralizar o cálculo compartilhado ou manter uma função auxiliar comum para que a tela e o PDF não implementem critérios divergentes. Inserir os valores resultantes no contexto existente e apresentá-los no resumo da tela, no resumo geral do PDF e no detalhamento por loja.
- Não há mudança de esquema nem migração; os filtros de loja já usados pelas views permanecem como estão e a métrica não cria nova autorização por querystring.

## Riscos / Trade-offs

- [Consultas adicionais por loja podem aumentar o tempo de renderização do relatório] → Preferir consulta agregada com contagem distinta e evitar consultas por cliente ou pagamento dentro de laços.
- [As duas views atualmente aplicam o período a partir de parcelas de formas separadas] → Compartilhar o critério da nova métrica e cobrir ambos os caminhos na validação.

## Plano de migração

Sem migração de dados ou implantação em etapas. Após a atualização, a métrica é calculada sob demanda nos relatórios existentes. O rollback consiste em reverter o código e as alterações dos templates; não há dados persistidos a reverter.
