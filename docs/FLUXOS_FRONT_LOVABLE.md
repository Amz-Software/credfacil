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
   - busca por nome (`search`);
   - filtro de repasse (`filter=pendente` / `filter=sem_pendente`), quando aplicável;
   - paginação para navegar entre resultados.
3. Na listagem, cada loja exibe:
   - nome da loja;
   - informação consolidada de repasses (incluindo repasses atrasados);
   - status de pendências;
   - ações disponíveis em card/linha.
4. Usuário pode executar as seguintes ações em cada loja:
   - **Visualizar detalhe**: abre tela com dados completos, repasses, vendas e KPIs;
   - **Editar**: abre formulário para atualizar dados cadastrais (nome, endereço, contatos, etc.);
   - **Criar nova loja**: botão flutuante/de ação abre formulário novo;
   - **Excluir loja**: ação com confirmação (se permissão `vendas.delete_loja`);
   - **Replicar QR Code/Código do app**: ação que copia `qr_code_aplicativo` e `codigo_aplicativo` da loja selecionada para todas as outras.

## 1.2 Regras de acesso e escopo

- Se o usuário **não** possui permissão de ver todas as lojas, ele vê somente a loja da sessão.
- Com permissão adequada, pode ver e gerenciar múltiplas lojas.

## 1.3 Detalhe da loja

Na tela de detalhe da loja existem, no mínimo, estes blocos:

### 1.3.1 Bloco de dados cadastrais
- Nome da loja
- CNPJ
- Endereço (rua, número, bairro, cidade, CEP)
- Telefone(s)
- Email
- QR Code do aplicativo (exibição e possibilidade de replicar)
- Código do aplicativo
- Contrato associado (link/referência)

**Ações disponíveis:**
- **Editar dados**: abre formulário modal ou inline para atualizar informações;
- **Salvar alterações**: valida campos obrigatórios e persiste mudanças;
- **Cancelar edição**: descarta alterações pendentes.

### 1.3.2 Bloco de Repasses
- Lista paginada de repasses da loja;
- Cada repasse exibe:
  - data do repasse;
  - valor;
  - status (`pendente`, `pago`, `cancelado`);
  - observações;
  - dias de atraso (se aplicável);
- Filtro por status (opcional);
- Busca por data ou valor (opcional).

**Ações disponíveis por repasse:**
- **Visualizar detalhe**: modal com informações completas do repasse;
- **Editar repasse**: modal de edição para alterar valor, data, status ou observação (exige permissão `financeiro.change_repasse`);
- **Excluir repasse**: ação com confirmação (exige permissão `financeiro.delete_repasse`);
- **Marcar como pago**: altera status para `pago` e registra data de pagamento;
- **Cancelar repasse**: marca como `cancelado` com motivo (exige permissão);
- **Criar novo repasse**: botão que abre formulário de novo repasse ao fim da lista.

### 1.3.3 Bloco de Vendas
- Lista paginada de vendas da loja (última 30 dias, com filtro de data disponível);
- Cada venda exibe:
  - data da venda;
  - cliente (nome);
  - vendedor (nome);
  - valor total;
  - status (normal, cancelada, trocada);
  - quantidade de itens.
- Filtros:
  - por data (`data_inicio` / `data_fim`);
  - por cliente (`cliente_nome`) - busca textual;
  - por vendedor;
  - mostrar/esconder vendas canceladas (`vendas_canceladas`);
  - mostrar/esconder vendas trocadas (`vendas_trocadas`).

**Ações disponíveis por venda:**
- **Visualizar detalhe**: abre página/modal com itens, pagamentos, parcelas e documentos;
- **Editar venda**: abre formulário de edição (se caixa aberto);
- **Ver documentos**: exibe/baixa documentos assinados, fotos, IMEI;
- **Cancelar venda**: marca como cancelada (se caixa aberto);
- **Trocar produto**: abre fluxo para substituição de item;
- **Gerar PDF/Nota**: gera e baixa documento da venda;
- **Gerar carnê**: gera e baixa carnê de parcelas.

### 1.3.4 Bloco de KPIs
- Quantidade total de vendas (período selecionado);
- Valor total vendido;
- Ticket médio;
- Valor total em repasses (período);
- Valor em repasses atrasados;
- Taxa de conversão (vendas/solicitações);
- Número de clientes ativos.

**Interações:**
- permitir alterar período de análise (`data_inicio` / `data_fim`);
- atualizar KPIs dinamicamente ao mudar período.

### 1.3.5 Formulário de novo Repasse
- Campos: valor, data, status, observação;
- Validações:
  - valor > 0;
  - data válida;
  - status obrigatório;
- **Ações:**
  - **Salvar repasse**: cria novo repasse e o exibe na lista;
  - **Cancelar**: fecha formulário sem criar.

## 1.4 Fluxo específico: replicar QR Code/código do app

### Pré-requisitos
- Usuário deve ter permissão `vendas.change_loja`;
- Loja selecionada ("fonte") possui preenchidos `qr_code_aplicativo` e `codigo_aplicativo`.

### Passos
1. Usuário clica em **"Replicar QR Code e Código"** na loja de origem.
2. Sistema exibe diálogo com:
   - lista de lojas destinatárias (todas as outras lojas ativas);
   - checkbox "Selecionar todas";
   - informação clara: "Valores de `qr_code_aplicativo` e `codigo_aplicativo` serão sobrescrevidos".
3. Usuário confirma seleção de lojas.
4. Clica em **"Confirmar replicação"**.
5. Sistema:
   - valida se a loja fonte possui ambos os campos;
   - copia para cada loja selecionada;
   - exibe mensagem de sucesso com quantidade de lojas atualizadas;
   - exibe erros (se houver lojas que falharam).
6. Usuário pode **"Cancelar"** antes de confirmar, que descarta a ação.

## 1.5 Estados e decisões para front

### Estado mínimo de listagem
- `search`: string de busca por nome;
- `filter`: `'pendente'` | `'sem_pendente'` | `null`;
- `page`: número de página atual;
- `pageSize`: itens por página;
- `permissoes`: objeto com flags de permissão:
  - `pode_criar_loja`: permissão `vendas.add_loja`;
  - `pode_editar_loja`: permissão `vendas.change_loja`;
  - `pode_deletar_loja`: permissão `vendas.delete_loja`;
  - `pode_ver_todas_lojas`: permissão `vendas.can_view_all_stores`;
  - `pode_ver_repasse`: permissão `financeiro.view_repasse`;
  - `pode_criar_repasse`: permissão `financeiro.add_repasse`.
- `lojas`: lista de lojas retornadas;
- `total`: quantidade total de lojas.

### Estado mínimo de detalhe
- `lojaId`: ID da loja selecionada;
- `loja`: objeto com dados cadastrais completos;
- `abas`: enum de abas abertas (`dados`, `repasses`, `vendas`, `kpis`);
- `modoEdicao`: boolean indicando se está editando dados cadastrais;
- `formularioRepasse`: objeto com dados do formulário de novo repasse;
- `repasses`: lista paginada de repasses;
- `vendas`: lista paginada de vendas;
- `filtrosVendas`: período selecionado para vendas (`data_inicio`, `data_fim`);
- `kpis`: objeto com valores calculados;
- `carregando`: boolean para telas carregando dados;
- `erros`: objeto com mensagens de erro por seção.

### Tratamento de permissões por ação
- **Listar lojas**: sempre disponível (respeitando escopo);
- **Criar loja**: habilitar botão se `pode_criar_loja === true`;
- **Editar loja**: habilitar botão se `pode_editar_loja === true`;
- **Excluir loja**: habilitar botão se `pode_deletar_loja === true`;
- **Replicar QR**: habilitar botão se `pode_editar_loja === true` e loja possui `qr_code_aplicativo` + `codigo_aplicativo`;
- **Ver/Criar repasses**: habilitar se `pode_ver_repasse === true` e `pode_criar_repasse === true` respectivamente;
- **Editar/Deletar repasses**: habilitar se usuário tem permissão `financeiro.change_repasse` / `financeiro.delete_repasse`.

### Validações client-side
- Campos obrigatórios de loja: nome, CNPJ.
- Repasse: valor > 0, data válida.
- Mensagens de erro inline em formulários.

---

## 2) Módulo **Venda**

## 2.1 Fluxo de listagem e consulta

1. Usuário abre **Lista de Vendas**.
2. Sistema exibe todas as vendas da loja(s) acessível(is), com opção de filtros:
   - **Busca por data**: exibe vendas de data específica ou intervalo;
   - **Filtro por loja** (se permissão `vendas.can_view_all_stores`): seleciona qual loja visualizar;
   - **Filtro por cliente** (`cliente_nome`): busca textual por nome do cliente;
   - **Filtro por vendedor**: seleciona vendedor específico;
   - **Toggle vendas canceladas** (`vendas_canceladas`): mostra/esconde vendas marcadas como canceladas;
   - **Toggle vendas trocadas** (`vendas_trocadas`): mostra/esconde vendas marcadas como trocadas;
   - **Paginação**: navega entre páginas de resultados.
3. Cada linha/card de venda exibe:
   - data da venda;
   - cliente (nome);
   - vendedor (nome);
   - valor total;
   - status visual (badge: normal, cancelada, trocada);
   - quantidade de itens.
4. Usuário pode clicar em qualquer linha para abrir **Detalhe da Venda**.

**Ações disponíveis na listagem:**
- **Visualizar detalhe**: clica na linha/card;
- **Criar nova venda**: botão flutuante/ação que abre formulário novo;
- **Aplicar filtros**: busca e refine a lista;
- **Limpar filtros**: reseta para vista padrão;
- **Exportar lista** (opcional): baixa CSV/Excel com vendas filtradas.

## 2.2 Fluxo de criação de venda (manual)

### Pré-requisitos
- Usuário possui permissão `vendas.add_venda`;
- Caixa está aberto para a loja da sessão;
- Cliente já existe ou será criado no ato da venda (depende da config).

### Passos (formato wizard recomendado)

#### Etapa 1: Dados Gerais
- **Cliente**: dropdown/busca pelos clientes existentes ou campo "Novo cliente" com sub-formulário;
- **Vendedor**: dropdown com vendedores da loja (pré-selecionado com usuário logado, se aplicável);
- **Loja**: pré-preenchida com loja da sessão (não editável);
- **Observação** (opcional): campo de texto livre para notas.

**Validações:**
- Cliente obrigatório;
- Vendedor obrigatório;
- Mensagem de erro se cliente não localizado.

**Ações:**
- **Próximo**: valida campos e avança para etapa 2;
- **Cancelar**: descarta rascunho e volta para listagem.

#### Etapa 2: Itens/Produtos
- **Tabela/List de itens** (inicialmente vazia):
  - coluna 1: Produto (dropdown com produtos ativos);
  - coluna 2: Quantidade (número, padrão 1);
  - coluna 3: Valor unitário (pode ser pré-preenchido do produto, editável);
  - coluna 4: Desconto (opcional, valor em R$);
  - coluna 5: Subtotal (calculado: qtd × unitário - desconto);
  - coluna 6: IMEI (dropdown/busca de IMEI em estoque, **obrigatório** em certas condições);
  - coluna 7: Ações (remover item).

- **Botão "Adicionar Item"**: abre linha nova ou modal para preenchimento.

**Validações por item:**
- Produto obrigatório;
- Quantidade > 0;
- Valor unitário > 0;
- IMEI obrigatório se produto for iPhone/Android (verificar tipo de produto);
- IMEI não pode estar associado a outra venda ativa.

**Ações:**
- **Adicionar item**: insere linha nova na tabela;
- **Remover item**: deleta linha com confirmação;
- **Editar item**: clica no item, re-abre modal de edição;
- **Próximo**: valida todos os itens (mínimo 1) e avança para etapa 3;
- **Anterior**: volta para etapa 1;
- **Cancelar**: descarta rascunho.

**Cálculos:**
- Total de itens: soma de todos os subtotais;
- Desconto total: soma de descontos aplicados;
- Valor bruto da venda: total de itens.

#### Etapa 3: Pagamentos e Parcelas
- **Tabela/List de pagamentos** (inicialmente vazia):
  - coluna 1: Tipo de pagamento (dropdown: dinheiro, débito, crédito, cheque, pix, **ENTRADA**, **IPX**);
  - coluna 2: Valor (número, em R$);
  - coluna 3: Número de parcelas (editável apenas se tipo suporta, ex. crédito/IPX);
  - coluna 4: Data da primeira parcela (datepicker, obrigatório se parcelado);
  - coluna 5: Ações (remover pagamento).

- **Botão "Adicionar Pagamento"**: abre linha ou modal de novo pagamento.

**Validações por pagamento:**
- Tipo obrigatório;
- Valor > 0;
- Número de parcelas > 0 se for parcelado;
- Data da primeira parcela válida e no futuro (ou hoje);
- Soma de pagamentos deve igualar valor bruto da venda (ou alertar diferença);
- Se há desconto aplicado, sistema distribui entre formas de pagamento proporcionalmente (ou permite ajuste manual).

**Ações:**
- **Adicionar pagamento**: insere linha;
- **Remover pagamento**: deleta linha;
- **Editar pagamento**: clica para modal;
- **Calcular parcelas**: ao validar, sistema gera lista de parcelas com datas (vencimentos, valores, prazos);
- **Próximo**: valida pagamentos vs. valor bruto, avança para etapa 4;
- **Anterior**: volta para etapa 2;
- **Cancelar**: descarta rascunho.

**Cálculos:**
- Total pago: soma de valores em pagamentos;
- Diferença: total pago - valor bruto (deve ser ≈ 0, alertar se não);
- Geração de parcelas: sistema cria cronograma com vencimentos, valores e status inicial.

#### Etapa 4: Revisão e Salvar
- **Resumo do pedido**:
  - cliente, vendedor, loja;
  - itens (tabela read-only);
  - pagamentos e parcelas (tabela read-only);
  - valor bruto, descontos, total de pagamentos.

- **Checklist pré-salvar**:
  - [ ] Caixa está aberto? (se não, mensagem de bloqueio);
  - [ ] Todos os itens válidos?
  - [ ] Soma de pagamentos = valor bruto?
  - [ ] Documentos podem ser anexados agora ou depois (flexível).

- **Opção de anexar documentos** (opcional nesta etapa):
  - upload de documento assinado;
  - upload de foto do cliente;
  - upload de imagem do IMEI.

**Ações:**
- **Salvar venda**: cria `Venda`, `ProdutoVenda`, `Pagamento` e gera `Parcela`s; exibe mensagem de sucesso e oferece opções:
  - voltar para listagem;
  - abrir detalhe da venda criada;
  - duplicar venda (novo rascunho com mesmos itens);
- **Anterior**: volta para etapa 3;
- **Cancelar**: descarta rascunho;
- **Salvar como rascunho**: salva estado parcial para retomar depois (opcional).

## 2.3 Fluxo de edição de venda

### Pré-requisitos
- Caixa está aberto para a loja;
- Usuário tem permissão `vendas.change_venda`;
- Venda não está cancelada (ou permite edição mesmo assim, conforme regra);
- Venda ainda não foi "finalizada" (não tem estado imutável).

### Tipos de edição

#### Edição padrão
- Usuário clica em **"Editar"** na tela de detalhe.
- Abre formulário similar ao wizard de criação, mas com dados pré-preenchidos.
- Permite alterar:
  - cliente (com cuidado para não quebrar relacionamentos);
  - vendedor;
  - observação;
  - **itens**: adicionar, remover ou editar quantidade/valor/desconto/IMEI;
  - **pagamentos**: adicionar, remover ou editar valor/parcelas/data.
- Ao salvar, sistema:
  - valida mesmas regras de criação;
  - recalcula parcelas se pagamentos foram alterados;
  - atualiza `ProdutoVenda` e `Pagamento`;
  - exibe mensagem de sucesso.

**Ações:**
- **Salvar alterações**: persiste mudanças;
- **Cancelar edição**: descarta alterações;
- **Voltar**: retorna para detalhe.

#### Edição especial
- Restrição maior de permissão: exige `vendas.pode_editar_especial` (customizado);
- Permet edição de campos normalmente bloqueados (ex.: datas, status de parcelas, etc.);
- Requer justificativa/motivo da alteração (auditoria);
- Fluxo similar, mas com campos adicionais de "motivo da alteração".

**Ações:**
- **Salvar com justificativa**: salva e loga mudança em auditoria;
- **Cancelar**: descarta.

### Validações de edição
- Caixa obrigatoriamente aberto;
- cliente/vendedor válidos;
- ao editar itens: IMEI não pode estar em outra venda ativa (exceto o IMEI atual do item);
- ao editar pagamentos: soma deve continuar = valor bruto;
- impossível editar venda cancelada (estado final) sem acesso especial.

## 2.4 Fluxo de cancelamento

### Pré-requisitos
- Caixa aberto;
- Usuário tem permissão `vendas.change_venda`;
- Venda não está já cancelada.

### Passos
1. Usuário clica em **"Cancelar venda"** na tela de detalhe ou listagem.
2. Sistema abre diálogo de confirmação com:
   - aviso: "Cancelar esta venda marcará como deleted e impactará caixa/estoque";
   - campo de motivo (obrigatório, ex.: "Arrependimento", "Dano no produto", "Transferência", etc.);
   - checkbox "Tenho certeza" para confirmar.
3. Se confirmar:
   - marca `is_deleted=True` na venda;
   - reverte itens para estoque (se rastreável);
   - reverte pagamentos (marca como cancelados ou anula registro);
   - exibe mensagem de sucesso.
4. Venda desaparece de listagens normais (pode haver filtro para "mostrar deletadas").

**Ações:**
- **Confirmar cancelamento**: executa operação;
- **Cancelar diálogo**: descarta ação.

## 2.5 Fluxo de documentos e detalhe

### Tela de Detalhe da Venda

Exibe seções:

#### Resumo da venda
- Cliente, vendedor, loja, data, status, observação;
- Valor bruto, descontos, total;
- **Ações rápidas**: editar, cancelar, gerar PDF.

#### Itens da venda
- Tabela read-only com: produto, quantidade, valor unitário, desconto, subtotal, IMEI, status;
- **Ação por item**:
  - **Ver detalhe do produto**: link para página do produto;
  - **Trocar produto** (se caixa aberto): abre fluxo de troca.

#### Pagamentos e Parcelas
- **Seção de Pagamentos**: tabela com tipo, valor, número de parcelas, data primeira parcela;
- **Seção de Parcelas**: tabela expandível com cronograma detalhado:
  - número da parcela;
  - data de vencimento;
  - valor;
  - status (`aberta`, `paga`, `atrasada`, `bloqueada`, `BO`, etc.);
  - **ações por parcela**:
    - **Informar pagamento**: marca como paga, registra data/comprovante;
    - **Confirmar quitação**: finaliza parcela;
    - **Bloquear/Desbloquear**: togla status de bloqueio;
    - **Registrar BO**: marca como "Boleto" ou "Protesto";
    - **Ver detalhes**: modal com histórico de alterações.

#### Seção de Documentos
- **Upload de arquivos** (se caixa aberto ou permissão especial):
  - documento assinado (PDF, imagem);
  - foto do cliente;
  - imagem do IMEI.
- **Visualização de arquivos** (se existentes):
  - miniatura/preview;
  - botão "Baixar";
  - botão "Deletar" (com confirmação);
  - botão "Substituir" (sobrescreve anexo).

#### Histórico/Auditoria
- Log de alterações (timestamp, usuário, campo alterado, antes/depois);
- Notas ou comentários internos (opcional).

**Ações na tela de detalhe:**
- **Editar venda**: volta para wizard de edição;
- **Edição especial**: abre formulário restrito (se permissão);
- **Cancelar venda**: abre diálogo;
- **Trocar produto**: abre fluxo (ver seção 2.6);
- **Informar pagamento (todos)**: atalho para marcar todas as parcelas em aberto como pagas;
- **Gerar PDF/Nota**: baixa documento da venda;
- **Gerar carnê**: baixa carnê de parcelas para cliente;
- **Imprimir**: envia para impressora;
- **Voltar**: retorna para listagem.

## 2.6 Fluxo financeiro acoplado à venda

### Gestão de Pagamentos e Parcelas

#### Estrutura de dados
- **Pagamento**: registro de forma de pagamento (dinheiro, débito, crédito, IPX, etc.) com valor total e número de parcelas;
- **Parcela**: cada fração de um pagamento parcelado, com:
  - número sequencial;
  - valor;
  - data de vencimento;
  - status;
  - histórico de alterações.

#### Status de Parcela
- `aberta`: aguardando pagamento;
- `paga`: pagamento confirmado;
- `atrasada`: vencimento passou e não foi paga;
- `bloqueada`: cliente bloqueado, parcela não pode ser recebida até desbloqueio;
- `BO`: Boleto enviado para protesto (status jurídico);
- `cancelada`: parcela anulada (ex. por cancelamento de venda).

#### Ações em Parcelas (individual)

**Informar Pagamento:**
- Clica em parcela aberta/atrasada;
- Abre modal com campos:
  - Data do pagamento (vs. data de vencimento, calcular juros se houver);
  - Valor recebido (pode diferir do valor original);
  - Forma de recebimento (dinheiro, depósito, cheque, pix, etc.);
  - Comprovante/observação (opcional).
- Sistema:
  - valida data e valor;
  - marca parcela como `paga`;
  - registra histórico;
  - exibe mensagem de sucesso.
- **Ações**: salvar, cancelar.

**Confirmar Quitação:**
- Marca parcela como definitivamente quitada;
- Desbloqueia possíveis vinculos (parcelas seguintes, caixa, etc.);
- Gera recibo/comprovante (opcional).
- **Ações**: confirmar, cancelar.

**Bloquear/Desbloquear:**
- Alterna status de bloqueio;
- Bloquear: impossibilita recebimento até desbloqueio manual;
- Desbloquear: retorna parcela para `aberta` ou `atrasada`.
- Requer motivo (default: "Bloqueio manual", customizável).
- **Ações**: aplicar, cancelar.

**Registrar BO (Boleto):**
- Marca parcela/pagamento como enviado para protesto;
- Abre modal com:
  - número do boleto;
  - data de envio;
  - banco/operadora;
  - observação.
- Sistema registra e muda status para `BO`;
- **Ações**: salvar, cancelar.

**Ver Detalhes:**
- Abre modal read-only com:
  - dados da parcela;
  - histórico completo de alterações (quem, quando, de/para);
  - comprovantes anexados;
  - notas internas.

#### Ações em Pagamentos (global)

**Informar Pagamento (Todos):**
- Botão atalho na tela de detalhe da venda;
- Marca **todas** as parcelas em aberto/atrasadas como pagas em uma ação;
- Requer confirmação antes de executar;
- Sistema:
  - itera sobre parcelas;
  - marca como `paga`;
  - usa data de hoje como data de pagamento;
  - exibe resumo (X parcelas marcadas como pagas).

**Recalcular Parcelas:**
- Se pagamentos foram editados, sistema pode regenerar cronograma de parcelas;
- Atalho "Recalcular" ou automático ao salvar edição;
- Valida se mudança de pagamento impacta parcelas existentes (avisa usuário).

**Gerar Documento de Cobrança:**
- Cria PDF padrão (notificação de vencimento, juros, etc.);
- Permite customizar template;
- Baixa ou imprime.

### Integração com Caixa
- Ao informar pagamento de parcela, sistema **não** atualiza caixa automaticamente;
- Existe fluxo separado de "fechar caixa" que consolida todos os pagamentos do dia;
- Importante: este documento de fluxos é sobre **vendas**; caixa é módulo separado.

### Indicadores e KPIs de Parcelas
- Total em aberto (value);
- Total atrasado (value + dias);
- Total bloqueado (value);
- Taxa de inadimplência (%);
- Previsão de recebimento (gráfico de cronograma).

## 2.7 Estados e decisões para front

### Modelo de estado de venda
A venda no front precisa tratar como "agregado" estruturado:

```
{
  venda: {
    id,
    cliente_id,
    cliente_nome,
    vendedor_id,
    vendedor_nome,
    loja_id,
    data_venda,
    observacao,
    valor_bruto,
    valor_desconto,
    valor_total,
    status_visual, // 'normal' | 'cancelada' | 'trocada'
    is_deleted,
    criado_em,
    atualizado_em
  },
  itens: [
    {
      id,
      produto_id,
      produto_nome,
      quantidade,
      valor_unitario,
      valor_desconto,
      subtotal,
      imei_associado,
      status
    }
  ],
  pagamentos: [
    {
      id,
      tipo_pagamento,
      valor,
      numero_parcelas,
      data_primeira_parcela,
      status
    }
  ],
  parcelas: [
    {
      id,
      pagamento_id,
      numero,
      valor,
      data_vencimento,
      data_pagamento,
      status, // 'aberta' | 'paga' | 'atrasada' | 'bloqueada' | 'BO' | 'cancelada'
      eh_atrasada,
      dias_atraso,
      bloqueada,
      comprovante_url
    }
  ],
  documentos: {
    documento_assinado_url,
    foto_cliente_url,
    imagem_imei_url
  },
  permissoes: {
    pode_editar: boolean,
    pode_editar_especial: boolean,
    pode_cancelar: boolean,
    pode_trocar_produto: boolean,
    pode_informar_pagamento: boolean,
    pode_gerar_pdf: boolean
  },
  ui: {
    modo_edicao: boolean,
    aba_ativa: 'resumo' | 'itens' | 'pagamentos' | 'documentos',
    carregando: boolean,
    erros: { campo: [mensagens] }
  }
}
```

### Validações client-side
- Cliente obrigatório;
- Vendedor obrigatório;
- Mínimo 1 item na venda;
- Soma de pagamentos ≈ valor bruto (alerta se diferir);
- IMEI obrigatório se tipo de produto exigir;
- IMEI único (não pode estar em outra venda ativa);
- Caixa obrigatoriamente aberto para criar/editar;
- Campos de restrição (ex.: data no futuro) validados com feedback imediato.

### Feedback visual
- **Spinner/loader** durante operações assíncronas;
- **Toast/snackbar** para sucesso/erro de ações;
- **Inline errors** em formulários (campo destacado + mensagem);
- **Badges** para status (normal, cancelada, trocada);
- **Indicadores de parcela atrasada** (cor vermelha, ícone, dias de atraso);
- **Modal de confirmação** para ações destrutivas (cancelar, excluir item, etc.).

### Pré-condições e bloqueios
- Edição bloqueada se caixa fechado → exibir mensagem com botão "Abrir caixa" com link direto;
- Criação bloqueada se caixa fechado → bloquear botão + tooltip explicativo;
- Ação "edição especial" bloqueada se sem permissão → botão desabilitado/oculto;
- Alteração de cliente: aviso de que pode quebrar relacionamentos.

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
- `EA` = **Em análise**: solicitação registrada, awaiting analista review.
- `A` = **Aprovado**: cliente liberado para fluxo operacional (app/iCloud).
- `R` = **Reprovado**: pedido negado, cliente não é elegível. Motivo deve estar documentado.
- `C` = **Cancelado**: solicitação cancelada (por cliente, vendedor ou sistema). Pode ter motivo.

### Status do aplicativo
- `P` = **Pendente**: cliente ainda não baixou/confirmou o app.
- `C` = **Confirmação pendente**: app foi baixado, mas confirmação de instalação pendente (fluxo intermediário).
- `I` = **Instalado**: app confirmado como instalado no device, pronto para próximos passos.

### Flags do fluxo iPhone
- `icloud_configurado_vendedor`: vendedor confirmou que configurou iCloud no device;
- `icloud_confirmado_analista`: analista validou a configuração de iCloud;
- `imei_informado`: IMEI foi registrado no sistema.

### Flags gerais
- `venda_gerada`: referência a venda (`Venda.id`) criada a partir dessa solicitação;
- `analise_online`: foi feita análise online (algum fluxo diferenciado);
- `obteve_contato`: vendedor confirmou contato com cliente;
- `obteve_contato_pessoal`: vendedor confirmou contato com referência pessoal;
- `consulta_serasa`: foi feita consulta de restrição junto a Serasa/SPC;
- `restricao`: cliente possui restrição identificada.

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

1. **Solicitação criada** → status `EA` (Em análise);
   - vendedor preenche formulário completo;
   - sistema valida documentos e informações básicas.

2. **Analista aprova** → status `A` (Aprovado);
   - análise de crédito feita offline ou em sistema externo;
   - cliente agora habilitado para app.

3. **Vendedor avança status do app**:
   - **Clica "Instalar app"** → status `C` (Confirmação pendente);
     - cliente lê QR e baixa app no device;
     - app envia notificação de confirmação pendente de volta.
   - **Clica "Confirmar leitura QR"** → status `I` (Instalado);
     - cliente confirmou que conseguiu validar iCloud (se aplicável) ou simplesmente abriu o app (Android);
     - sistema agora permite que analista informa IMEI.

4. **Analista informa IMEI**:
   - Clica **"Informar IMEI"** na solicitação;
   - Abre modal para input de IMEI (pode ser input manual ou leitura de código);
   - Sistema valida:
     - IMEI formato válido (15 dígitos);
     - IMEI não está associado a outra venda ativa;
     - se IMEI existe em estoque da loja, associa; senão cria novo registro de estoque IMEI.
   - Após informar, status aplicativo passa para `I` automaticamente (se ainda não).

5. **Pré-requisitos atendidos**:
   - ✓ Análise aprovada (`status_analise = 'A'`);
   - ✓ App instalado (`status_aplicativo = 'I'`);
   - ✓ IMEI informado;
   - ✓ Caixa aberto;
   - ✓ Validação de CPF (máximo de vendas/parcelas pagas conforme IPX).

6. **Gerar venda**:
   - Vendedor clica **"Gerar venda"** (ou "Finalizar solicitação");
   - Sistema valida todos os pré-requisitos;
   - Se OK:
     - cria `Venda` vinculada a essa análise;
     - cria `ProdutoVenda` com IMEI;
     - cria `Pagamento` (ENTRADA + IPX);
     - gera `Parcela`s conforme prazo;
     - associa venda na análise (`analise.venda = venda.id`);
     - exibe mensagem de sucesso + link para detalhe da venda.

### Validações críticas Android
- `status_aplicativo` deve estar em `I` (Instalado) para gerar venda;
- IMEI obrigatoriamente preenchido e único;
- CPF: validar histórico de vendas (máximo parcelas pagas).

### Ações disponíveis no fluxo Android
- **Instalar app** (vendedor): `POST /api/solicitacoes/{cliente_id}/instalar-app/`
- **Confirmar leitura QR** (vendedor): `POST /api/solicitacoes/{cliente_id}/confirmar-app/`
- **Informar IMEI** (analista): `POST /api/solicitacoes/analises/{analise_id}/informar-imei/`
- **Confirmar instalação** (analista): `POST /api/solicitacoes/{cliente_id}/analista-confirmar-instalacao/`
- **Gerar venda** (vendedor): `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

## 3.5 Fluxo iPhone

### Pré-requisitos adicionais
- Cliente deve fornecer (ou ter acesso a):
  - email iCloud;
  - senha iCloud.
- Essa informação é preenchida no formulário inicial ou durante análise.

Sequência típica:

1. **Solicitação criada** → status `EA` (Em análise);
   - vendedor preenche com campos especiais: `email_icloud`, `senha_icloud`;
   - validações básicas de formato.

2. **Analista aprova** → status `A` (Aprovado);
   - análise valida se email/senha foram informados;
   - se não, pode bloquear aprovação com mensagem "iCloud obrigatório para iPhone".

3. **Vendedor configura iCloud**:
   - **Clica "Configurar iCloud (Vendedor)"** → `icloud_configurado_vendedor = True`;
     - vendedor acessa device do cliente;
     - usa email/senha fornecida(s) para fazer login no iCloud;
     - ativa find my iphone/localizador;
     - volta e clica para confirmar que fez essa configuração.
   - Sistema registra timestamp e usuário.

4. **Analista confirma iCloud**:
   - **Clica "Confirmar iCloud (Analista)"** → `icloud_confirmado_analista = True`;
     - analista valida con backend/servidor que iCloud foi configurado corretamente;
     - pode incluir verificação de segurança ou chamada para Apple DDM (Device Deployment Manager);
     - sistema marca como confirmado.
   - Pré-requisito: `icloud_configurado_vendedor = True`.

5. **Analista informa IMEI**:
   - **Clica "Informar IMEI"** (após iCloud confirmado);
   - Modal com input/leitura de IMEI;
   - Sistema valida:
     - IMEI formato correto (15 dígitos);
     - IMEI não em outra venda;
     - **validação especial iPhone**: exige `icloud_confirmado_analista = True`;
   - Associa ou cria estoque IMEI.

6. **Pré-requisitos atendidos**:
   - ✓ Análise aprovada (`status_analise = 'A'`);
   - ✓ Email e senha iCloud preenchidos;
   - ✓ iCloud configurado por vendedor;
   - ✓ iCloud confirmado por analista;
   - ✓ IMEI informado;
   - ✓ Caixa aberto;
   - ✓ Validações CPF (IPX).

7. **Status aplicativo** (automático):
   - Não há fluxo de "app pendente/confirmação" como em Android;
   - uma vez que iCloud está confirmado e IMEI informado, sistema marca `status_aplicativo = 'I'`.

8. **Gerar venda**:
   - Vendedor clica **"Gerar venda"** ou "Finalizar solicitação";
   - Sistema valida todos os pré-requisitos específicos de iPhone;
   - Se OK:
     - cria venda, produto venda, pagamentos, parcelas;
     - associa análise com venda.

### Validações críticas iPhone
- Email e senha iCloud obrigatórios;
- `icloud_configurado_vendedor = True` obrigatoriamente antes de analista confirmar;
- `icloud_confirmado_analista = True` obrigatoriamente antes de gerar venda;
- IMEI informado obrigatoriamente;
- CPF: validação de histórico de vendas.

### Ações disponíveis no fluxo iPhone
- **Configurar iCloud (Vendedor)**: `POST /api/solicitacoes/{cliente_id}/configurar-icloud/`
- **Confirmar iCloud (Analista)**: `POST /api/solicitacoes/{cliente_id}/analista-confirm-icloud/`
- **Informar IMEI** (analista, com validação iPhone): `POST /api/solicitacoes/analises/{analise_id}/informar-imei/`
- **Gerar venda** (vendedor): `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

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

## 3.6 Geração de venda a partir da solicitação

### Fluxo geral (Android e iPhone)

**Acionador:**
- Vendedor clica **"Gerar venda"** ou "Finalizar solicitação" na tela de detalhe da solicitação.

### Validações, na ordem
1. **Autenticação e permissão**:
   - usuário deve estar autenticado;
   - exige permissão `vendas.add_venda`.

2. **Dados básicos**:
   - cliente_id válido e existente;
   - loja_id válido e existente (vem da sessão);
   - solicitação (análise) deve existir e não estar deletada.

3. **Status da análise**:
   - `status_analise` deve ser `'A'` (Aprovado);
   - se status for outro (`EA`, `R`, `C`), bloqueia com mensagem clara.

4. **Histórico de CPF**:
   - sistema busca todas as vendas do cliente.cpf no histórico;
   - conta quantas parcelas foram pagas de vendas anteriores;
   - validação IPX (ex.: "máximo de 3 vendas simultâneas ou até 2 parcelas pagas");
   - se falhar, bloqueia com mensagem específica (ex.: "Cliente já possui 2 vendas em aberto, máximo é 3").

5. **Validações específicas por tipo de produto**:
   - **Android**:
     - `status_aplicativo` deve ser `'I'` (Instalado);
     - IMEI obrigatoriamente informado (`analise.imei_informado` não null);
     - IMEI não pode estar associado a outra venda ativa.
   - **iPhone**:
     - `icloud_configurado_vendedor = True`;
     - `icloud_confirmado_analista = True`;
     - IMEI obrigatoriamente informado;
     - IMEI único (não em outra venda).

6. **Caixa**:
   - caixa da loja deve estar aberto;
   - se fechado, bloqueia com botão "Abrir caixa".

7. **Venda já gerada**:
   - verificar se `analise.venda_id` já está preenchida;
   - se sim, alerta "Venda já foi criada para essa solicitação" com link para venda existente.

### Criação de venda (se todas validações passarem)

1. **Cria objeto Venda**:
   - `cliente_id = solicitacao.cliente_id`;
   - `vendedor_id = usuario_logado.id` (ou permite seleção);
   - `loja_id = sessao.loja_id`;
   - `data_venda = hoje`;
   - `observacao = "Gerada a partir da solicitação de crédito #{solicitacao.id}"` (ou vazio);
   - `valor_bruto, valor_desconto, valor_total = calculados`.

2. **Cria ProdutoVenda**:
   - `produto_id = solicitacao.produto_id`;
   - `quantidade = 1` (padrão para crédito);
   - `valor_unitario = solicitacao.valor_produto` (ou preço atual do produto);
   - `imei_id = encontrar IMEI pelo IMEI informado na solicitação`.

3. **Cria Pagamentos**:
   - **ENTRADA**: valor da entrada (primeira parcela ou percentual);
   - **IPX**: restante dividido em parcelas (conforme `solicitacao.numero_parcelas`).
   - calcula datas de vencimento com base em `solicitacao.data_pagamento` (dia do mês) e cadência (mensal).

4. **Cria Parcelas**:
   - gera cronograma completo de parcelas a partir dos pagamentos;
   - cada parcela com número sequencial, valor, vencimento, status inicial `'aberta'`.

5. **Vincula na solicitação**:
   - `analise.venda_id = venda.id`;
   - `analise.status_analise = 'A'` (mantém);
   - registra timestamp de geração.

### Resposta ao usuário

**Se sucesso:**
- mensagem: "Venda #{venda_id} criada com sucesso!";
- opções:
  - **"Ver venda"**: link direto para detalhe da venda criada;
  - **"Voltar à listagem"**: fecha e retorna para lista de solicitações;
  - **"Imprimir carnê"**: abre doc de carnê.

**Se falha:**
- mensagem descritiva do motivo:
  - "Análise não está aprovada";
  - "Cliente já possui limite de vendas";
  - "IMEI não foi informado";
  - "App não foi confirmado como instalado";
  - "iCloud não foi confirmado";
  - "Caixa está fechado para essa loja" (com botão "Abrir caixa");
  - etc.
- botão "Tentar novamente" ou "Voltar".

### Campos do solicitacao necessários para geração
- `cliente_id` (obrigatório);
- `produto_id` (obrigatório);
- `numero_parcelas` (obrigatório);
- `data_pagamento` (dia do mês, obrigatório);
- `imei_informado` (obrigatório para gerar venda);
- `status_analise = 'A'` (obrigatório);
- Para iPhone: `email_icloud`, `senha_icloud`, `icloud_configurado_vendedor`, `icloud_confirmado_analista` (obrigatórios);
- Para Android: `status_aplicativo = 'I'` (obrigatório).

## 3.7 Ações de aprovação/reprovação/cancelamento

### Aprovar Análise

**Pré-requisitos:**
- Usuário no grupo `ANALISTA` ou `ADMINISTRADOR`;
- Solicitação em status `EA` (Em análise).

**Passos:**
1. Clica em **"Aprovar"** na tela de detalhe.
2. Sistema abre modal de confirmação com:
   - resumo do cliente e produto;
   - validação extra para iPhone:
     - se tipo de produto é iPhone, valida se `email_icloud` e `senha_icloud` estão preenchidos;
     - exibe mensagem de bloqueio se não.
   - campo de observação/motivo (opcional);
   - checkbox "Confirmar aprovação".
3. Clica em **"Confirmar"**:
   - sistema marca `status_analise = 'A'`;
   - registra timestamp e usuário;
   - envia notificações:
     - para vendedor (cliente foi aprovado);
     - para admin (log de auditoria).
4. Exibe mensagem de sucesso.

**Ações:**
- **Confirmar aprovação**: marca como aprovado;
- **Cancelar**: descarta;
- **Voltar**: retorna para detalhe.

### Reprovar Análise

**Pré-requisitos:**
- Usuário no grupo `ANALISTA` ou `ADMINISTRADOR`;
- Solicitação em status `EA` (Em análise).

**Passos:**
1. Clica em **"Reprovar"** na tela de detalhe.
2. Sistema abre modal de rejeição com:
   - campo de motivo/razão (obrigatório):
     - dropdown com causas comuns:
       - "Renda insuficiente";
       - "Restrição de crédito";
       - "CPF irregular";
       - "Documentação incompleta";
       - "Outro (especifique)";
   - campo de texto livre para detalhe;
   - checkbox "Confirmar reprovação".
3. Clica em **"Confirmar"**:
   - sistema marca `status_analise = 'R'`;
   - armazena motivo em campo de observação;
   - registra timestamp e usuário;
   - envia notificações:
     - para vendedor (cliente foi reprovado + motivo);
     - para admin (log).
   - sistema pode disparar ação automática: armazenar cliente em blacklist (opcional).
4. Exibe mensagem de sucesso.

**Ações:**
- **Confirmar reprovação**: marca como reprovado;
- **Cancelar**: descarta;
- **Voltar**: retorna para detalhe.

### Cancelar Análise

**Pré-requisitos:**
- Usuário no grupo `VENDEDOR`, `ANALISTA` ou `ADMINISTRADOR`;
- Solicitação em status `EA`, `A` ou `R` (não cancelada ainda).

**Passos:**
1. Clica em **"Cancelar solicitação"** na tela de detalhe.
2. Sistema abre modal de confirmação com:
   - aviso: "Esta ação marcará a solicitação como cancelada e não poderá ser revertida";
   - campo de motivo/razão (obrigatório):
     - dropdown com causas comuns:
       - "Cliente desistiu";
       - "Solicitação duplicada";
       - "Cliente já possui venda ativa";
       - "Outro (especifique)";
   - campo de texto livre para detalhe;
   - checkbox "Tenho certeza".
3. Clica em **"Cancelar solicitação"**:
   - sistema marca `status_analise = 'C'`;
   - armazena motivo;
   - bloqueia qualquer avanço no fluxo dessa solicitação;
   - registra timestamp e usuário;
   - envia notificações:
     - para vendedor (solicitação cancelada);
     - para admin (log).
4. Exibe mensagem de sucesso.

**Ações:**
- **Confirmar cancelamento**: marca como cancelado;
- **Cancelar diálogo**: descarta;
- **Voltar**: retorna para detalhe.

## 3.8 Estados e decisões para front

### Timeline visual de etapas

1. **Cadastro** - dados + documentos
2. **Análise** - EA/A/R/C
3. **App/iCloud** - Android ou iPhone
4. **IMEI** - se aplicável
5. **Venda** - geração final

### Bloqueios de UI

- **Aprovar**: status='EA' AND user in [ANALISTA, ADMIN]
- **Reprovar**: status='EA' AND user in [ANALISTA, ADMIN]
- **Cancelar**: status≠'C' AND user in [VENDEDOR, ANALISTA, ADMIN]
- **Configurar iCloud**: status='A' AND tipo=iPhone AND user=VENDEDOR
- **Confirmar iCloud**: config=true AND status='A' AND user=ANALISTA
- **Informar IMEI**: status='A' AND user=ANALISTA
- **Gerar Venda**: pré-req ok AND venda_id=null AND caixa aberto

### Feedback visual

- Toast/snackbar para ações
- Badges de status (cores: EA=amarelo, A=verde, R=vermelho, C=cinza)
- Timeline colorida de progresso
- Indicadores de bloqueio (cadeado + tooltip)
- Modal de confirmação para ações críticas
- Erros inline em formulários
- Venda gerada (sim/não)

Recomendação prática: renderizar ações por etapa com bloqueio contextual (botões habilitados/desabilitados) em vez de menu “solto”.

---

## 4) Módulo **Produto**

## 4.1 Fluxo de listagem e consulta

1. Usuário abre **Lista de Produtos**.
2. Sistema exibe todos os produtos visiveis (conforme permissões):
   - Se usuário tem `produtos.view_all_produtos`: vê ativos + inativos.
   - Demais usuários: veem apenas produtos ativos (`ativo=True`).
3. Podem usar:
   - **Busca por nome** (`search`): filtra em tempo real;
   - **Filtro por status** (ativo/inativo) - opcional, depende de permissão;
   - **Paginação** para navegar entre resultados;
   - **Ordenação** por nome, preço ou data de criação.
4. Cada linha/card de produto exibe:
   - nome do produto;
   - tipo de dispositivo (iPhone, Android, acessório, etc.);
   - preço (valor de venda padrão);
   - status visual (badge: ativo, inativo);
   - quantidade em estoque (opcional, se integração com estoque);
   - ações disponíveis.
5. Usuário pode clicar em qualquer linha para abrir **Detalhe do Produto**.

**Ações disponíveis na listagem:**
- **Visualizar detalhe**: clica na linha/card;
- **Criar novo produto**: botão flutuante/ação que abre formulário novo;
- **Editar produto**: ícone de lápis (se permissão `produtos.change_produto`);
- **Ativar/Desativar**: toggle ou botão (se permissão `produtos.change_produto`);
- **Deletar produto**: ação com confirmação (se permissão `produtos.delete_produto`);
- **Aplicar filtros**: refine a lista;
- **Limpar filtros**: reseta para vista padrão.

## 4.2 Detalhe do produto

Na tela de detalhe do produto, exibe:

### Bloco de dados cadastrais
- Nome do produto (editável);
- Descrição (texto livre, editável);
- Tipo de dispositivo/categoria (ex.: iPhone 12, iPhone 12 Pro, Android genérico, etc.);
- Preço de venda padrão (valor em R$, editável);
- SKU ou código interno (opcional, editável);
- Status (ativo|inativo) com toggle visual;
- Data de criação e última atualização (read-only);
- Imagem/foto do produto (upload, opcional).

**Ações disponíveis:**
- **Editar dados**: abre formulário modal ou inline para atualizar informações;
- **Salvar alterações**: valida campos e persiste mudanças;
- **Cancelar edição**: descarta alterações pendentes;
- **Ativar/Desativar**: toggle de status.

### Bloco de informações operacionais
- **Tipo de dispositivo**: ex. "iPhone", "Android", "Acessório";
  - Afeta se IMEI é obrigatório em vendas que usam esse produto.
- **É iPhone**: boolean (sim/não);
  - Marca especial se produto é iPhone (afeta validações de iCloud).
- **Requer IMEI**: boolean (sim/não);
  - Se "sim", em vendas que usam esse produto, campo IMEI é obrigatório.
- **Aplicável a crédito**: boolean (sim/não);
  - Se "sim", produto pode ser usado em "Solicitação de crédito".
- **Preço mínimo** (opcional): limite inferior para descontos em vendas.
- **Preço máximo** (opcional): limite superior para sobretaxação.

### Bloco de Opções de Parcelamento (valores por nº de parcelas)
Para cada produto, é possível definir valores específicos de parcelamento IPX (a prazo):

- **Entrada do cliente**: valor da primeira entrada (à vista);
- **Valor para 4X**: preço total se parcelado em 4 vezes;
- **Valor para 6X**: preço total se parcelado em 6 vezes;
- **Valor para 8X**: preço total se parcelado em 8 vezes;
- **Valor para 10X**: preço total se parcelado em 10 vezes;
- **Valor para 12X**: preço total se parcelado em 12 vezes;
- **Valor para 14X**: preço total se parcelado em 14 vezes.

**Observação:** Esses valores são pré-configurados para o produto. Ao criar uma venda, o sistema pode usar esses valores como referência ou permitir customização por venda. Em solicitações de crédito, o número de parcelas é definido durante a solicitação e o valor é calculado ou selecionado conforme essa tabela.

- **Valor de Repasse (Logista)**: valor que a loja recebe de repasse por venda deste produto (administrativo/configurar).

### Bloco de histórico de uso
- **Quantidade de vendas** (read-only): total de vezes que esse produto foi vendido;
- **Valor total vendido** (read-only): somatório de valores de vendas com esse produto;
- **Número de solicitações de crédito** (read-only): quantas solicitações usam esse produto;
- **Última venda** (read-only): data/hora da última venda com esse produto;
- **Data de criação** (read-only).

**Interações:**
- Essa seção é apenas informativa (leitura);
- link "Ver vendas" que direciona para listagem de Vendas, filtrada por produto.

## 4.3 Fluxo de criação de produto

### Pré-requisitos
- Usuário possui permissão `produtos.add_produto`.

### Passos

1. Usuário clica em **"Criar novo produto"** na listagem ou tela de detalhe.
2. Sistema abre formulário modal ou página de criação com campos:
   - **Nome** (obrigatório): nome do produto;
   - **Descrição** (opcional): detalhes adicionais;
   - **Tipo de dispositivo** (dropdown, obrigatório):
     - opções: "iPhone", "Android", "Acessório", "Outro";
   - **É iPhone** (checkbox): marca se é produto iPhone (afeta iCloud);
   - **Fabricante** (dropdown, obrigatório): fabricante do produto;
   - **Requer IMEI** (checkbox): indica se IMEI é obrigatório em vendas;
   - **Aplicável a crédito** (checkbox): permite uso em solicitações de crédito;
   - **Preço de venda padrão** (número, obrigatório, > 0);
   - **Entrada do cliente** (número, valor da entrada à vista);
   - **Valores de parcelamento** (números, opcionais):
     - Valor 4X, 6X, 8X, 10X, 12X, 14X;
   - **Valor de repasse (Logista)** (número, opcional): margem da loja;
   - **SKU/Código** (texto, opcional): código interno;
   - **Imagem** (upload, opcional): foto do produto.

**Validações client-side:**
- Nome obrigatório;
- Tipo de dispositivo obrigatório;
- Preço > 0;
- Preço deve ser um número válido;
- Mensagens de erro inline em tempo real.

**Ações:**
- **Salvar produto**: cria novo produto e exibe mensagem de sucesso;
  - oferece opções:
    - voltar para listagem;
    - editar produto criado;
    - criar outro produto (limpa formulário);
- **Cancelar**: descarta rascunho e volta para listagem ou tela anterior.

## 4.4 Fluxo de edição de produto

### Pré-requisitos
- Usuário tem permissão `produtos.change_produto`;
- Produto já existe.

### Passos

1. Usuário clica em **"Editar"** na tela de detalhe ou listagem.
2. Sistema abre formulário com dados pré-preenchidos:
   - nome, descrição, tipo, é iPhone, fabricante, requer IMEI, aplicável a crédito, preço padrão, entrada, valores de parcelas (4X-14X), repasse, SKU, imagem.
3. Usuário pode alterar qualquer campo:
   - **Restrições**:
     - Nome não pode ficar vazio;
     - Preço deve ser > 0;
     - Tipo de dispositivo não pode virar "vazio".
4. Clica em **"Salvar alterações"**:
   - Sistema valida campos;
   - Se OK, persiste mudanças;
   - exibe mensagem de sucesso.
5. Usuário pode **"Cancelar edição"** para descartar alterações.

**Ações:**
- **Salvar alterações**: persiste mudanças;
- **Cancelar edição**: descarta alterações;
- **Voltar**: retorna para detalhe.

### Validações de edição
- Campos obrigatórios não podem estar vazios;
- Preço > 0;
- Tipo de dispositivo deve ser válido.

## 4.5 Ativação/Desativação

### Fluxo de Ativação

**Pré-requisitos:**
- Usuário tem permissão `produtos.change_produto`;
- Produto está com `ativo=False`.

**Passos:**
1. Usuário clica em **"Ativar"** (botão/toggle) na tela de detalhe ou listagem.
2. Sistema abre diálogo rápido de confirmação:
   - aviso: "Ativar este produto o tornará disponível para vendas e solicitações".
3. Usuário confirma.
4. Sistema:
   - marca `ativo=True`;
   - registra timestamp;
   - produto agora aparece em listas de produtos "ativos" em formulários de venda/solicitação abertos;
   - exibe mensagem de sucesso.

**Ações:**
- **Confirmar ativação**: marca como ativo;
- **Cancelar**: descarta ação.

### Fluxo de Desativação

**Pré-requisitos:**
- Usuário tem permissão `produtos.change_produto`;
- Produto está com `ativo=True`.

**Passos:**
1. Usuário clica em **"Desativar"** (botão/toggle) na tela de detalhe ou listagem.
2. Sistema abre diálogo de confirmação com:
   - aviso: "Desativar este produto o removerá de novas vendas/solicitações, mas não afeta vendas já criadas";
   - motivo (opcional): campo para justificar desativação;
   - checkbox "Tenho certeza".
3. Usuário confirma.
4. Sistema:
   - marca `ativo=False`;
   - registra timestamp e motivo;
   - produto desaparece de dropdowns em formulários de novo venda/solicitação;
   - já não aparece em listas normais (pode haver filtro para "mostrar inativos");
   - exibe mensagem de sucesso.

**Ações:**
- **Confirmar desativação**: marca como inativo;
- **Cancelar**: descarta ação.

## 4.6 Estados e decisões para front

### Modelo de estado de listagem

```
{
  search: string,
  filterAtivo: boolean | null,
  page: number,
  pageSize: number,
  ordenacao: 'nome' | 'preco' | 'criacao',
  direcao: 'asc' | 'desc',
  permissoes: {
    pode_criar_produto: boolean,
    pode_editar_produto: boolean,
    pode_deletar_produto: boolean,
    pode_ver_inativos: boolean
  },
  produtos: [
    {
      id,
      codigo,
      nome,
      tipo_dispositivo,
      preco_padrao: decimal,
      entrada_cliente: decimal,
      valor_4_vezes: decimal,
      valor_6_vezes: decimal,
      valor_8_vezes: decimal,
      valor_10_vezes: decimal,
      valor_12_vezes: decimal,
      valor_14_vezes: decimal,
      eh_iphone: boolean,
      ativo: boolean,
      criado_em
    }
  ],
  total: number,
  carregando: boolean,
  erros: object
}
```

### Modelo de estado de detalhe

```
{
  produtoId: number,
  produto: {
    id,
    codigo,
    nome,
    tipo_dispositivo,
    eh_iphone: boolean,
    preco_padrao: decimal,
    entrada_cliente: decimal,
    valor_4_vezes: decimal,
    valor_6_vezes: decimal,
    valor_8_vezes: decimal,
    valor_10_vezes: decimal,
    valor_12_vezes: decimal,
    valor_14_vezes: decimal,
    valor_repasse_logista: decimal,
    sku,
    imagem_url,
    ativo: boolean,
    requer_imei: boolean,
    aplicavel_credito: boolean,
    criado_em: datetime,
    atualizado_em: datetime
  },
  historico: {
    quantidade_vendas: number,
    valor_total_vendido: number,
    numero_solicitacoes_credito: number,
    ultima_venda_data: datetime,
    primeira_venda: datetime
  },
  modoEdicao: boolean,
  permissoes: {
    pode_editar: boolean,
    pode_deletar: boolean,
    pode_ativar_desativar: boolean
  },
  ui: {
    carregando: boolean,
    erros: { campo: [mensagens] }
  }
}
```

### Tratamento de permissões por ação
- **Listar produtos**: sempre disponível (ativos=sempre, inativos=se `pode_ver_inativos`);
- **Criar produto**: habilitar botão se `pode_criar_produto === true`;
- **Editar produto**: habilitar botão se `pode_editar_produto === true`;
- **Deletar produto**: habilitar botão se `pode_deletar_produto === true`;
- **Ativar/Desativar**: habilitar toggle se `pode_editar_produto === true`.

### Validações client-side
- Nome obrigatório e não vazio;
- Tipo de dispositivo obrigatório;
- Preço > 0 e número válido;
- SKU (opcional) pode ser qualquer string;
- Mensagens de erro inline em formulários.

### Feedback visual
- **Spinner/loader** durante carregamento ou operações assíncronas;
- **Toast/snackbar** para sucesso/erro de ações (criar, editar, ativar/desativar);
- **Inline errors** em formulários (campo destacado + mensagem);
- **Badge de status** para ativo/inativo (cores: ativo=verde, inativo=cinza);
- **Modal de confirmação** para ações destrutivas (deletar, desativar);
- **Link "Ver vendas"** no bloco histórico para navegar para listagem de vendas filtrada por produto.

### Pré-condições e bloqueios
- **Criar produto**: sem bloqueios além de permissão;
- **Editar produto**: sem bloqueios além de permissão;
- **Deletar produto**: bloquear se o produto tem vendas/solicitações associadas (mostrar motivo: "Produto já foi usado em vendas");
- **Desativar produto**: sem bloqueios, apenas aviso de que não aparecerá em novos formulários;
- **Ativar produto**: sem bloqueios, apenas confirmação.

---

## 5) Proposta de estrutura para o front no Lovable

## 5.1 Módulo Loja
- **Tela Lista**: filtros + cards/linhas + ação de detalhar.
- **Tela Detalhe**: dados, repasses, vendas, KPI, ação de replicar QR/código.
- **Tela Form**: criar/editar.

## 5.2 Módulo Venda
- **Tela Lista** com filtros e paginação.
- **Tela Form (wizard opcional)**:
  - etapa 1: dados gerais
  - etapa 2: itens
  - etapa 3: pagamentos/parcelas
  - etapa 4: revisão e salvar
- **Tela Detalhe** com documentos e ações.

## 5.3 Módulo Solicitação de crédito
- **Tela Lista (Kanban ou tabela)** com KPIs e filtros.
- **Tela Detalhe da solicitação** com timeline de etapas:
  - Cadastro
  - Análise
  - Fluxo App/iCloud
  - IMEI
  - Geração de venda
- **Ações orientadas por etapa e perfil** (vendedor x analista x admin).

## 5.4 Módulo Produto
- **Tela Lista**: search + filtro de status (ativo/inativo) + ordenação + paginação.
- **Tela Detalhe**: dados cadastrais, histórico de uso, status ativo/inativo.
- **Tela Form**: criar/editar com campos de nome, descrição, tipo, preço, IMEI obrigatório, aplicável a crédito.

---

## 6) Checklist funcional para você transformar em plano de construção

- [ ] Mapear permissões por ação e por perfil.
- [ ] Definir estados de tela para “loja ativa”.
- [ ] Definir componentes de status (badges, timeline, bloqueios).
- [ ] Definir validações client-side equivalentes às regras de backend.
- [ ] Planejar mensagens de erro/sucesso por etapa.
- [ ] Priorizar fluxo de solicitação→venda como trilha principal (maior regra de negócio).

---

## 7) Resumo rápido (para kickoff)

- **Loja** = cadastro + governança de repasses + visão consolidada de vendas.
- **Venda** = transação composta por itens/pagamentos/parcelas, fortemente ligada ao caixa.
- **Solicitação de crédito** = funil operacional com múltiplos estados até virar venda.
- **Produto** = catálogo de items vendáveis com atributos (IMEI, tipo, preço) + histórico de uso.

Com esse mapeamento, você já consegue quebrar o front do Lovable em épicos, telas e estados antes de plugar API.

**Observação importante:** Produto é a "peça central" que conecta solicitações de crédito a vendas. Garanta que o flow de criação/seleção de produtos seja simples e intuitivo em formulários de venda e solicitação.
