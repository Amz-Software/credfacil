# Fluxo Completo de Solicitacao de Credito (Especificacao para Lovable)

Este documento e a referencia funcional para implementar o modulo de solicitacao de credito no frontend (Lovable), alinhado ao comportamento atual do backend.

## 1) Visao geral do funil

A solicitacao de credito segue este funil:

1. Selecao de produto e condicoes
2. Preenchimento dos dados do cliente
3. Envio de comprovantes
4. Criacao da solicitacao (status inicial: `EA`)
5. Decisao da analise (`A`, `R`, `C`)
6. Fluxo operacional por tipo de produto:
- Android: app/confirmacoes + IMEI
- iPhone: iCloud vendedor + confirmacao analista + IMEI
7. Geracao da venda

Resultado final esperado:

- `analise_credito.venda` preenchido com o id da venda criada.

## 2) Atores e responsabilidades

- `VENDEDOR`
- cria/edita solicitacao
- executa etapas operacionais (instalacao app / configurar iCloud)
- gera venda quando liberado

- `ANALISTA`
- aprova/reprova/cancela analise
- confirma etapas tecnicas (iCloud / instalacao)
- informa IMEI

- `ADMINISTRADOR`
- pode ter acesso as mesmas acoes conforme permissoes

Regra importante:

- O frontend pode esconder botoes por perfil, mas a seguranca final sempre e do backend.

## 3) Estados do processo

## 3.1 Status da analise (`analise_credito.status`)

- `EA`: Em analise
- `A`: Aprovado
- `R`: Reprovado
- `C`: Cancelado

## 3.2 Status do app (`analise_credito.status_aplicativo`)

- `P`: Pendente
- `C`: Confirmacao pendente
- `I`: Instalado

## 3.3 Flags especificas iPhone

- `email_icloud`
- `senha_icloud`
- `icloud_configurado_vendedor` (bool)
- `icloud_confirmado_analista` (bool)

## 3.4 Flags gerais de progresso

- `imei` (fk de estoque)
- `imei_informado` (string)
- `venda` (id da venda)

## 4) Telas e ordem real de preenchimento

## 4.1 Tela de listagem de solicitacoes

Objetivo:

- mostrar pipeline de solicitacoes e seus status.

Dados minimos por card/linha:

- cliente
- produto
- status analise
- status app
- sinalizacao de venda gerada

Filtros recomendados:

- `search`
- `status`
- `status_app`
- `analise_online`
- `loja`
- `data_inicio` / `data_fim`
- `vendas_nao_finalizadas`

Endpoint:

- `GET /api/solicitacoes/`

## 4.2 Tela de criacao/edicao (ordem oficial das abas)

Ordem correta no sistema atual:

1. `Produto` (primeira etapa obrigatoria)
2. `Dados`
3. `Comprovantes`

### Aba 1: Produto

Campos principais:

- `produto`
- `numero_parcelas`
- `data_pagamento`
- `entrada_informada` (iPhone)
- `analise_online` (opcional)
- `email_icloud` e `senha_icloud` (se produto iPhone)

Comportamento esperado:

- ao trocar produto, recalcular condicoes exibidas
- produto iPhone ativa validacoes extras de iCloud
- produto iPhone exibe campo de entrada (`entrada_informada`)
- sem produto selecionado, nao considerar etapa concluida

### Regra de entrada no iPhone

- Todo iPhone usa entrada minima cadastrada em `produto.entrada_cliente`.
- Operador pode informar `entrada_informada` na aba Produto.
- Se `entrada_informada` vier vazia, o sistema considera automaticamente a entrada minima.
- Se `entrada_informada` for menor que a entrada minima, o frontend deve alertar e o backend bloqueia a venda.
- Esta regra e exclusiva do fluxo iPhone.

### Aba 2: Dados

Blocos internos:

- dados do cliente
- informacao pessoal
- contato adicional

Validacoes relevantes:

- evitar duplicidade entre contatos/enderecos/nomes de referencias quando aplicavel
- validar campos obrigatorios

### Aba 3: Comprovantes

Campos de arquivo:

- documento frente
- documento verso
- comprovante de residencia
- foto do cliente
- outros campos conforme permissao/perfil

Observacao tecnica:

- criacao/edicao com arquivo deve usar `multipart/form-data`.

## 4.3 Tela de detalhe da solicitacao

Objetivo:

- acompanhar timeline do processo
- exibir o que falta para liberar venda
- centralizar acoes operacionais

Componentes recomendados:

- bloco de status atual
- checklist de pre-requisitos
- bloco de acoes por perfil
- historico de mudancas

## 5) Fluxo detalhado Android

Pre-condicao: produto selecionado nao e iPhone.

1. Criar solicitacao
- endpoint: `POST /api/solicitacoes/`
- status esperado apos sucesso: `EA`

2. Aprovar analise
- endpoint: `POST /api/solicitacoes/{cliente_id}/aprovar/`
- status esperado: `A`

3. Etapa de app (vendedor)
- `POST /api/solicitacoes/{cliente_id}/instalar-app/`
- `POST /api/solicitacoes/{cliente_id}/confirmar-app/`
- estado de trabalho: `status_aplicativo = C`

4. Informar IMEI (analista)
- endpoint: `POST /api/solicitacoes/{cliente_id}/informar-imei-analise/`
- payload:
```json
{
  "imei_informado": "123456789012345"
}
```
- efeito esperado no Android: backend marca `status_aplicativo = I`

5. (Opcional operacional) Confirmar instalacao final
- endpoint: `POST /api/solicitacoes/{cliente_id}/analista-confirmar-instalacao/`

6. Gerar venda
- endpoint: `POST /api/solicitacoes/{cliente_id}/gerar-venda/`
- retorno esperado: objeto de venda criado (201)

## 6) Fluxo detalhado iPhone

Pre-condicao: produto selecionado e iPhone.

1. Criar solicitacao com dados iCloud
- endpoint: `POST /api/solicitacoes/`
- campos obrigatorios operacionais:
- `email_icloud`
- `senha_icloud`
- `entrada_informada` (opcional no payload, respeitando minimo quando enviada)

2. Aprovar analise
- endpoint: `POST /api/solicitacoes/{cliente_id}/aprovar/`
- sem iCloud preenchido, backend pode bloquear

3. Vendedor configura iCloud
- endpoint: `POST /api/solicitacoes/{cliente_id}/configurar-icloud/`
- resultado: `icloud_configurado_vendedor = true`

4. Analista confirma iCloud
- endpoint: `POST /api/solicitacoes/{cliente_id}/analista-confirm-icloud/`
- pre-condicao: vendedor ja confirmou
- resultado: `icloud_confirmado_analista = true`

5. Analista informa IMEI
- endpoint: `POST /api/solicitacoes/{cliente_id}/informar-imei-analise/`
- pre-condicao: iCloud confirmado pelo analista

6. Gerar venda
- endpoint: `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

### Regra financeira iPhone (entrada + juros)

Na geracao da venda iPhone, o backend usa:

1. `valor_base = produto.valor` (obrigatorio para iPhone)
2. `entrada_usada = entrada_informada` (se informada) senao `produto.entrada_cliente`
3. valida `entrada_usada >= produto.entrada_cliente`
4. `valor_financiado = valor_base - entrada_usada`
5. busca juros na tabela `Parcelamento` por `qtd_vezes = numero_parcelas`
6. `valor_credfacil = valor_financiado + (valor_financiado * porcentagem_juros / 100)`

Impacto nos pagamentos criados:

- Pagamento `ENTRADA` recebe `entrada_usada`
- Pagamento `IPX` recebe `valor_credfacil`

## 7) Matriz de botoes no detalhe (regra de UI)

## 7.1 Acoes comuns

- `Aprovar`: mostrar para analista/perfil autorizado quando status `EA`
- `Reprovar`: mostrar para analista/perfil autorizado quando status `EA`
- `Cancelar`: mostrar para perfil autorizado quando status diferente de `C`
- `Informar IMEI`: mostrar para analista quando solicitacao estiver apta por tipo de fluxo
- `Gerar venda`: mostrar para vendedor quando todos pre-requisitos forem verdadeiros

## 7.2 Acoes Android

- `Instalar app`: mostrar quando status analise `A` e produto Android
- `Confirmar app`: mostrar quando status analise `A` e produto Android
- `Confirmar instalacao (analista)`: mostrar para analista no fluxo Android

## 7.3 Acoes iPhone

- `Configurar iCloud`: mostrar para vendedor quando status analise `A` e iPhone
- `Confirmar iCloud`: mostrar para analista quando `icloud_configurado_vendedor = true`

## 8) Regras de bloqueio para gerar venda

Bloquear `Gerar venda` se qualquer condicao abaixo falhar:

- `analise_credito.status != 'A'`
- `analise_credito.imei` ausente
- Android: `analise_credito.status_aplicativo != 'I'`
- iPhone: sem email/senha iCloud
- iPhone: `icloud_configurado_vendedor != true`
- iPhone: `icloud_confirmado_analista != true`
- iPhone: `entrada_informada < produto.entrada_cliente`
- iPhone: produto sem `valor` base
- iPhone: parcelamento (`qtd_vezes`) nao cadastrado
- `analise_credito.venda` ja preenchido
- caixa da loja fechado
- IMEI em uso em outra venda
- regra de historico CPF nao atendida

## 9) Contrato de API para frontend

Base de trabalho:

- recurso: `/api/solicitacoes/`
- detalhe: sempre usar `{cliente_id}`

## 9.1 Endpoints principais

- `GET /api/solicitacoes/`
- `GET /api/solicitacoes/{cliente_id}/`
- `POST /api/solicitacoes/`
- `PUT /api/solicitacoes/{cliente_id}/`
- `PATCH /api/solicitacoes/{cliente_id}/`
- `POST /api/solicitacoes/{cliente_id}/aprovar/`
- `POST /api/solicitacoes/{cliente_id}/reprovar/`
- `POST /api/solicitacoes/{cliente_id}/cancelar/`
- `POST /api/solicitacoes/{cliente_id}/informar-imei-analise/`
- `POST /api/solicitacoes/{cliente_id}/gerar-venda/`

## 9.2 Endpoints operacionais Android

- `POST /api/solicitacoes/{cliente_id}/instalar-app/`
- `POST /api/solicitacoes/{cliente_id}/confirmar-app/`
- `POST /api/solicitacoes/{cliente_id}/analista-confirmar-instalacao/`

## 9.3 Endpoints operacionais iPhone

- `POST /api/solicitacoes/{cliente_id}/configurar-icloud/`
- `POST /api/solicitacoes/{cliente_id}/analista-confirm-icloud/`

## 9.4 Exemplo de payload de criacao

```json
{
  "nome": "Fulano",
  "telefone": "11999999999",
  "cpf": "12345678900",
  "nascimento": "1990-01-01",
  "rg": "1234567",
  "cep": "01001000",
  "endereco": "Rua A",
  "bairro": "Centro",
  "cidade": "Sao Paulo",
  "profissao": "Vendedor",
  "quantidade_dependentes": 0,
  "recebe_auxilio": false,
  "total_renda": "3500.00",
  "nome_adicional": "Beltrano",
  "contato": "11988887777",
  "endereco_adicional": "Rua B",
  "nome_pessoal": "Ciclano",
  "contato_pessoal": "11977776666",
  "endereco_pessoal": "Rua C",
  "produto": 1,
  "numero_parcelas": "6",
  "data_pagamento": "10",
  "entrada_informada": "500.00",
  "analise_online": false,
  "email_icloud": "cliente@icloud.com",
  "senha_icloud": "senha-temporaria"
}
```

Observacao:

- para envio real com arquivos, usar `multipart/form-data`.

## 9.5 Validacoes adicionais de criacao/edicao para iPhone

Na criacao/edicao de solicitacao com produto iPhone, a API tambem valida:

- se existe tabela de `Parcelamento` cadastrada no sistema;
- se existe `Parcelamento` para o `numero_parcelas` escolhido.

Sem essas configuracoes, a API retorna erro de validacao e nao salva a solicitacao.

## 10) Tratamento de erro e UX recomendados no Lovable

Em qualquer acao de escrita:

1. executar chamada
2. tratar erro e mostrar mensagem amigavel
3. em sucesso, recarregar detalhe (`GET /api/solicitacoes/{cliente_id}/`)

Mensagens de erro comuns que devem aparecer na UI:

- sem permissao
- status invalido para etapa atual
- iCloud obrigatorio para iPhone
- IMEI obrigatorio/duplicado
- caixa fechado
- solicitacao ja convertida em venda

Boas praticas visuais:

- desabilitar botao enquanto request em andamento
- mostrar loading por acao
- usar toasts para sucesso
- manter checklist sempre sincronizado com o retorno do backend

## 11) Sequencia recomendada de implementacao no frontend

1. Listagem + filtros + detalhe
2. Formulario (aba Produto, Dados, Comprovantes)
3. Acoes da analise (aprovar/reprovar/cancelar)
4. Fluxo Android
5. Fluxo iPhone
6. Modal de IMEI
7. Bloqueios de gerar venda
8. Refino de mensagens e estados de carregamento

## 12) Referencias

- Documentacao geral da API: `docs/API.md`
- Documentacao interativa: `GET /api/docs/`
- OpenAPI JSON: `GET /api/schema/`
