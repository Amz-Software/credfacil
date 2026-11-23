# Delta da especificação

## Purpose

Define a interface do backoffice React: identidade visual a partir da logo, navegação, padrões de lista, detalhe e ação, tempo real, acessibilidade e migração por módulo.

## ADDED Requirements

### Requirement: Paleta da logo com contraste AA
A interface MUST usar como cor primária o amarelo da logo (`#FFDD21`), como neutros a escala "tinta" derivada do preto da logo, e MUST atender contraste WCAG AA em todo par de texto e fundo, nos modos claro e escuro.

#### Cenário: Botão primário
- **QUANDO** um botão primário for exibido
- **ENTÃO** terá fundo amarelo-500 e texto tinta-900 (contraste ≥ 4,5:1)

#### Cenário: Texto em amarelo
- **QUANDO** um texto precisar de destaque na cor da marca sobre fundo claro
- **ENTÃO** usará amarelo-800 (`#8A6600`), nunca amarelo-500

#### Cenário: Alerta não confunde com a marca
- **QUANDO** um status de alerta for exibido
- **ENTÃO** usará o laranja de alerta, com ícone e texto, distinto do amarelo primário

#### Cenário: Modo escuro
- **QUANDO** o usuário escolher o modo escuro ou o sistema estiver em modo escuro
- **ENTÃO** todas as telas usarão os tokens escuros, sem cor fixa no código das telas

### Requirement: Navegação por domínio e por permissão
O menu MUST agrupar as telas em Início, Crédito, Vendas, Financeiro, Atendimento, Relatórios, Catálogo e Administração, e MUST exibir cada item somente a quem tem a permissão correspondente. A interface é só conforto: a autorização efetiva é a do servidor.

#### Cenário: Atendente do CRM
- **QUANDO** um usuário com `crm.acessar_crm` e sem permissões financeiras entrar
- **ENTÃO** verá Atendimento e não verá Financeiro

#### Cenário: Rota digitada sem permissão
- **QUANDO** um usuário abrir diretamente a URL de uma tela que não pode acessar
- **ENTÃO** verá a tela de acesso negado, e a API também recusará os dados

### Requirement: Seletor de loja e busca global
A barra superior MUST oferecer seletor de loja (limitado ao escopo do usuário, com "Todas" só para quem tem permissão global) e busca global por cliente (nome ou CPF), venda (número) e IMEI, aberta por Ctrl+K.

#### Cenário: Troca de loja
- **QUANDO** o usuário trocar a loja ativa
- **ENTÃO** as telas abertas recarregarão os dados com o novo `X-Loja`, e os filtros da URL serão mantidos

### Requirement: Padrão único de lista
Toda lista MUST manter os filtros na URL, mostrar chips de filtro ativo, paginar e ordenar no servidor, exibir skeleton ao carregar e estado vazio com ação, e mascarar o CPF.

#### Cenário: Compartilhar busca
- **QUANDO** o usuário copiar a URL de uma lista filtrada e abri-la em outra aba
- **ENTÃO** a lista abrirá com os mesmos filtros, página e ordenação

### Requirement: Decisões com confirmação e motivo
Reprovar ou cancelar análise, cancelar venda, quitar, fazer edição especial e excluir registros MUST pedir confirmação. As decisões de análise e o cancelamento de venda MUST exigir motivo, enviado à auditoria.

#### Cenário: Reprovar sem motivo
- **QUANDO** o analista tentar reprovar sem preencher o motivo
- **ENTÃO** o botão de confirmar ficará indisponível e nada será enviado

### Requirement: Fila de análise em tempo real
A fila de análise MUST se atualizar por eventos do WebSocket, sem polling fixo quando a conexão estiver ativa, e MUST ordenar por tempo de espera com cronômetro visível.

#### Cenário: Nova proposta
- **QUANDO** um vendedor criar uma solicitação na loja do escopo do analista
- **ENTÃO** a fila mostrará a nova solicitação sem recarregar a página, e o analista com `change_status_analise` verá o aviso central de nova proposta

#### Cenário: WebSocket indisponível
- **QUANDO** a conexão cair
- **ENTÃO** a fila atualizará a cada 30 s enquanto a aba estiver visível e tentará reconectar com espera crescente

### Requirement: Impressos gerados no servidor
Nota, carnê, contrato, BO e relatórios MUST ser PDFs gerados no servidor, com o mesmo conteúdo dos documentos atuais.

#### Cenário: Carnê
- **QUANDO** o usuário pedir o carnê de uma venda
- **ENTÃO** receberá um PDF com as parcelas e o QR PIX de cada uma, sem depender de script de terceiros no navegador

### Requirement: Acessibilidade
As telas MUST ser operáveis só pelo teclado, com foco visível, rótulos em todos os campos e status com texto ou ícone além da cor (meta WCAG 2.2 AA).

#### Cenário: Navegação por teclado na fila
- **QUANDO** o analista usar J/K na fila
- **ENTÃO** a seleção mudará de solicitação com foco visível, e A/R abrirão a confirmação de aprovar ou reprovar

### Requirement: Migração por módulo com reserva
Cada módulo MUST ser ligado na SPA por `BACKOFFICE_SPA_MODULOS`. Enquanto o módulo estiver desligado, as telas Django continuam ativas. A sessão MUST ser a mesma nas duas interfaces.

#### Cenário: Módulo ligado
- **QUANDO** `credito` estiver em `BACKOFFICE_SPA_MODULOS`
- **ENTÃO** as telas Django de solicitações redirecionarão para a rota equivalente em `/painel/`, sem pedir novo login

#### Cenário: Rollback
- **QUANDO** `credito` for retirado da variável
- **ENTÃO** as telas Django voltarão a responder normalmente
