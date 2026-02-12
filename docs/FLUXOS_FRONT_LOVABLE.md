# Fluxos funcionais do sistema web atual (base para front no Lovable)

> Objetivo: descrever **como o sistema web já funciona hoje** (não API), para orientar a construção do front por módulo.

---

## 0) Contexto global de navegação (impacta todos os módulos)

- O sistema trabalha com **loja selecionada em sessão** (`session['loja_id']`) no login.
- Essa loja em sessão restringe listagens, cadastros e ações quando o usuário não tem permissão de ver tudo.
- Portanto, no front novo vale modelar sempre:
  - `lojaAtiva`
  - `permissoesDoUsuario`
  - `filtrosPorLoja`

---

## 1) Módulo **Loja**

## 1.1 Fluxo principal

1. Usuário acessa **Lista de Lojas**.
2. Pode usar:
   - busca por nome;
   - filtro de repasse (`pendente` / `sem pendente`), quando aplicável.
3. Na listagem, cada loja exibe informação de repasses (incluindo atrasos).
4. Usuário pode:
   - criar nova loja;
   - editar loja existente;
   - abrir detalhe da loja.

## 1.2 Regras de acesso e escopo

- Se o usuário **não** possui permissão de ver todas as lojas, ele vê somente a loja da sessão.
- Com permissão adequada, pode ver e gerenciar múltiplas lojas.

## 1.3 Detalhe da loja

Na tela de detalhe da loja existem, no mínimo, estes blocos:

- dados cadastrais + contrato;
- lista de repasses (paginada);
- lista de vendas da loja (paginada, com filtro por data);
- KPIs (quantidade de vendas, valor total, valor de repasse);
- formulário para novo repasse.

## 1.4 Fluxo específico: replicar QR Code/código do app

1. Usuário seleciona uma loja “fonte”.
2. Sistema valida se a loja fonte possui `qr_code_aplicativo` e `codigo_aplicativo`.
3. Se válido, replica esses dois campos para todas as outras lojas.
4. Exibe mensagem de sucesso/erro.

## 1.5 Estados e decisões para front

- Estado mínimo de listagem: `search`, `filter`, paginação, permissões.
- Estado mínimo de detalhe: abas/cards para `dados`, `repasses`, `vendas`, `kpis`.
- Ação de replicação deve ter confirmação (impacto em massa).

---

## 2) Módulo **Venda**

## 2.1 Fluxo de listagem e consulta

1. Usuário abre listagem de vendas.
2. Pode filtrar por loja (quando tem permissão), datas e busca.
3. A listagem já considera regra de escopo por loja/permissão.

## 2.2 Fluxo de criação de venda (manual)

1. Usuário abre tela “Nova venda”.
2. Sistema usa form principal + formsets de:
   - itens/produtos da venda;
   - formas de pagamento.
3. Ao salvar:
   - vincula loja da sessão;
   - calcula/salva itens e pagamentos;
   - gera/atualiza parcelas conforme forma de pagamento;
   - depende de caixa aberto para operação.

## 2.3 Fluxo de edição de venda

- Existe edição padrão e edição especial.
- Em ambos os casos, a atualização envolve:
  - dados básicos da venda;
  - produtos da venda;
  - pagamentos.
- Com caixa fechado, edição é bloqueada.

## 2.4 Fluxo de cancelamento

- Venda pode ser marcada como cancelada (`is_deleted=True`) por ação específica.
- Esse estado impacta listagens, caixa e indicadores.

## 2.5 Fluxo de documentos e detalhe

- Há rota para atualizar documentos da venda (arquivo assinado/foto/IMEI imagem).
- Há detalhe da venda.
- Há geração de PDF/nota/contrato e carnê.

## 2.6 Fluxo financeiro acoplado à venda

- Pagamentos possuem parcelas e status complementares (bloqueio, atraso, BO, etc.).
- Existem ações de:
  - informar pagamento (individual/todos);
  - confirmar quitação;
  - toggles de status operacionais.

## 2.7 Estados e decisões para front

- A venda no front precisa tratar como “agregado”:
  - `cabecalhoVenda`
  - `itens[]`
  - `pagamentos[]`
  - `parcelas[]`
- Validar pré-condições de edição/criação com feedback imediato:
  - caixa aberto;
  - permissões;
  - consistência de itens/pagamentos.

---

## 3) Módulo **Solicitação de crédito** (fluxo real da tela de Clientes)

> No sistema atual, o fluxo está na área **Clientes/Solicitações**, não em um app separado.

## 3.1 Fluxo macro

1. Usuário clica em **Solicitar Crédito**.
2. Cadastra cliente + documentos + informações adicionais + análise.
3. Solicitação entra como **Em análise**.
4. Analista aprova/reprova/cancela.
5. Após aprovação, segue fluxo operacional por tipo de produto:
   - Android (app + confirmação + IMEI)
   - iPhone (iCloud vendedor + confirmação analista + IMEI)
6. Quando pré-requisitos são atendidos, usuário gera venda a partir da solicitação.

## 3.2 Status principais

### Status da análise
- `EA` = Em análise
- `A` = Aprovado
- `R` = Reprovado
- `C` = Cancelado

### Status do aplicativo
- `P` = Pendente
- `C` = Confirmação pendente
- `I` = Instalado

## 3.3 Filtros da listagem de solicitações

A listagem permite filtrar por:

- busca por nome;
- status da análise;
- análise online;
- status do aplicativo;
- loja;
- período;
- solicitações sem venda finalizada.

Além disso, a tela exibe KPIs por status.

## 3.4 Fluxo Android (não iPhone)

Sequência típica:

1. Solicitação aprovada.
2. Vendedor avança status de app (pendente → confirmação pendente/instalado conforme ação).
3. Analista informa IMEI.
4. Status fica apto para gerar venda quando regras estiverem ok.

Validação crítica para gerar venda Android:

- `status_aplicativo` precisa estar em `I` (instalado).

## 3.5 Fluxo iPhone

Sequência típica:

1. Solicitação aprovada.
2. Solicitação precisa ter `email_icloud` e `senha_icloud`.
3. Vendedor confirma configuração de iCloud.
4. Analista confirma iCloud.
5. Analista informa IMEI.
6. Solicitação fica pronta para gerar venda.

Validações críticas para gerar venda iPhone:

- email/senha iCloud preenchidos;
- iCloud configurado pelo vendedor;
- iCloud confirmado pelo analista.

## 3.6 Geração de venda a partir da solicitação

Ao clicar em “Gerar venda”, o sistema valida, em ordem prática:

1. requisição POST + permissões;
2. cliente/loja válidos;
3. restrição por CPF: vendas anteriores do mesmo CPF precisam ter ao menos 3 parcelas pagas (IPX);
4. análise aprovada;
5. IMEI informado;
6. regras Android/iPhone (app/iCloud);
7. solicitação ainda não convertida (`analise.venda` vazio);
8. existência de caixa aberto para a loja da análise;
9. IMEI não pode já estar em outra venda.

Se passar em tudo, sistema:

- cria `Venda`;
- cria item `ProdutoVenda`;
- cria pagamentos (`ENTRADA` + `IPX`);
- gera parcelas;
- vincula a venda na análise.

## 3.7 Ações de aprovação/reprovação/cancelamento

- Aprovar análise (com validações extras para iPhone).
- Reprovar análise.
- Cancelar análise.

## 3.8 Estados e decisões para front

Para o Lovable, esse módulo pede uma UI de **máquina de estados**:

- Estado da análise (`EA/A/R/C`)
- Estado do app (`P/C/I`)
- Flags iCloud (`configurado_vendedor`, `confirmado_analista`)
- IMEI informado (sim/não)
- Venda gerada (sim/não)

Recomendação prática: renderizar ações por etapa com bloqueio contextual (botões habilitados/desabilitados) em vez de menu “solto”.

---

## 4) Proposta de estrutura para o front no Lovable

## 4.1 Módulo Loja
- **Tela Lista**: filtros + cards/linhas + ação de detalhar.
- **Tela Detalhe**: dados, repasses, vendas, KPI, ação de replicar QR/código.
- **Tela Form**: criar/editar.

## 4.2 Módulo Venda
- **Tela Lista** com filtros e paginação.
- **Tela Form (wizard opcional)**:
  - etapa 1: dados gerais
  - etapa 2: itens
  - etapa 3: pagamentos/parcelas
  - etapa 4: revisão e salvar
- **Tela Detalhe** com documentos e ações.

## 4.3 Módulo Solicitação de crédito
- **Tela Lista (Kanban ou tabela)** com KPIs e filtros.
- **Tela Detalhe da solicitação** com timeline de etapas:
  - Cadastro
  - Análise
  - Fluxo App/iCloud
  - IMEI
  - Geração de venda
- **Ações orientadas por etapa e perfil** (vendedor x analista x admin).

---

## 5) Checklist funcional para você transformar em plano de construção

- [ ] Mapear permissões por ação e por perfil.
- [ ] Definir estados de tela para “loja ativa”.
- [ ] Definir componentes de status (badges, timeline, bloqueios).
- [ ] Definir validações client-side equivalentes às regras de backend.
- [ ] Planejar mensagens de erro/sucesso por etapa.
- [ ] Priorizar fluxo de solicitação→venda como trilha principal (maior regra de negócio).

---

## 6) Resumo rápido (para kickoff)

- **Loja** = cadastro + governança de repasses + visão consolidada de vendas.
- **Venda** = transação composta por itens/pagamentos/parcelas, fortemente ligada ao caixa.
- **Solicitação de crédito** = funil operacional com múltiplos estados até virar venda.

Com esse mapeamento, você já consegue quebrar o front do Lovable em épicos, telas e estados antes de plugar API.
