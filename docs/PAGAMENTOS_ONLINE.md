# Pagamentos online (PagBank)

App Django `pagamentos_online`. O cliente paga por Pix, boleto ou cartão uma parcela, várias parcelas da mesma compra numa cobrança só, ou a quitação da compra com o desconto do plano. O PagBank avisa o sistema pelo webhook e o sistema dá baixa sozinho, anexa um comprovante em PDF e avisa a equipe e o cliente.

## Regras

- **O valor vem sempre da parcela no banco** (`valor_restante`), nunca de quem pede.
- **A taxa fica com o cliente, menos no Pix.**
  - Boleto: soma a tarifa fixa.
  - Cartão: o total é calculado "por dentro" (`valor ÷ (1 − taxa%)`), para a empresa receber o valor cheio. Os juros do parcelamento são do comprador, que é o padrão do PagBank.
- **Tipos de cobrança** (`Cobranca.tipo`):
  - `parcela`: uma parcela.
  - `parcelas`: várias parcelas da mesma compra, sem desconto.
  - `quitacao`: todas as parcelas em aberto, com o `porcentagem_desconto` do pagamento distribuído proporcionalmente; a última parcela absorve o arredondamento, como na confirmação manual.

  As parcelas cobradas ficam em `ItemCobranca`, com o `valor` que entra em cada uma e o `desconto`. `Cobranca.parcela` é a primeira delas e `valor_parcela` é a soma dos itens. A taxa da forma de pagamento incide sobre essa soma.
- **Baixa de cobrança agrupada:** percorre os itens em ordem de parcela.
  - **Quitação paga por inteiro:** o desconto reduz o `valor` de cada parcela (como na confirmação manual), todas ficam pagas e o `Pagamento` fica `quitado`.
  - **Pago a menor:** credita em ordem sem desconto e anota para acerto.
  - **Parcela já paga no meio do caminho:** o valor dela vira excedente para acerto.
  - **Comprovante:** o mesmo PDF é anexado em cada parcela.
- **Não gera cobrança:**
  - quando o valor é zero;
  - quando alguma parcela já foi "informada" pelo cliente e aguarda a conferência da equipe, para evitar pagar duas vezes. A quitação online também some do app nesse caso.
- **A cobrança é reaproveitada.** Se já existe uma pendente e válida para o mesmo valor, ela volta em vez de criar outra.
- **A baixa só acontece depois de consultar o pedido** (`GET /orders/{id}`). O corpo da notificação não basta, e a assinatura `x-authenticity-token` é obrigatória. Se o mesmo pagamento chegar duas vezes, não há baixa em dobro. Se a parcela já estava paga, a cobrança fica marcada como `pagamento_duplicado` para acerto manual.
- **A baixa manual continua existindo** para o Pix do carnê (QR fixo com a chave da empresa), transferência e dinheiro. Ela usa o campo `Parcela.origem_baixa` (`pagbank`, `pix_carne`, `transferencia`, `dinheiro`, `cartao_loja`, `outro`).
- **Conciliação:** o `crm_rotinas` consulta as cobranças Pix e boleto pendentes a cada 5 minutos e expira as vencidas. Pix e cartão expiram 1 hora depois da validade; boleto, 5 dias depois, por causa da compensação. Os registros com mais de 180 dias são apagados.
- **Homologação:** toda chamada e toda notificação ficam em `RegistroPagBank`, com requisição e resposta e nunca com o token. Elas aparecem em `GET /api/bo/v1/cobrancas_online/registros/`.

## Configuração do servidor (`.env`)

```bash
PAGBANK_TOKEN=...            # token da conta (sandbox ou produção)
PAGBANK_AMBIENTE=sandbox     # sandbox | producao
PAGBANK_TIMEOUT=20           # segundos (opcional)
```

O restante é configurado no backoffice (`ConfiguracaoPagamentoOnline`): ligar e desligar, formas aceitas, taxas, máximo de parcelas no cartão, validade, dias do boleto, e-mail padrão (para cliente sem e-mail), UF padrão do boleto, endereço do app do cliente e redirecionamento das páginas antigas.

A URL do webhook é montada com o `url_publica` do CRM: `https://<url_publica>/api/pagbank/notificacao/`.

## API pública: app do cliente (`/api/publico/v1/`)

Não exige login. O acesso é pelo CPF com a data de nascimento, ou pelo `token` (UUID4) do pagamento.
- **Erros** vêm no formato `{"erro": {"codigo", "mensagem"}}`.
- **Escritas** são limitadas pelo escopo `publico`, de 20 por minuto por IP. As leituras usam o limite `anon`.
- **Valores em dinheiro** são strings com 2 casas (`"100.00"`). As datas seguem ISO 8601.

| Método | Caminho | O que faz |
|---|---|---|
| POST | `consulta/` `{cpf, data_nascimento}` (`dd/mm/aaaa` ou `aaaa-mm-dd`) | `{pagamentos: [{token, produto, parcelas_total, parcelas_abertas, parcelas_atrasadas, encerrado}]}` |
| GET | `pagamentos/<token>/` | Detalhe (abaixo) |
| GET | `pagamentos/<token>/opcoes/?parcelas=1,2` ou `?quitacao=1` | `{tipo, valor, desconto, parcelas: [{id, numero, valor, desconto}], opcoes: [...]}` |
| POST | `pagamentos/<token>/cobrancas/` `{forma, parcelas: [ids]}` ou `{forma, quitacao: true}` | 201 com a cobrança agrupada (exatamente um dos dois) |
| GET | `pagamentos/<token>/parcelas/<id>/opcoes/` | `{opcoes: [{forma, rotulo, valor_parcela, taxa, total, max_parcelas_cartao}]}` |
| POST | `pagamentos/<token>/parcelas/<id>/cobrancas/` `{forma: pix\|boleto\|cartao}` | 201 com a cobrança |
| GET | `pagamentos/<token>/cobrancas/<referencia>/` | Cobrança (para acompanhar enquanto o cliente paga) |
| GET | `pagamentos/<token>/cobrancas/<referencia>/comprovante/` | PDF (só para cobrança paga) |
| POST | `pagamentos/<token>/parcelas/<id>/informar/` (multipart, `comprovante` opcional) | Marca "pagamento informado" e devolve o detalhe |
| POST | `pagamentos/<token>/informar-quitacao/` | Coloca as parcelas em aberto em confirmação e devolve o detalhe |

**Detalhe do pagamento:**
```json
{
  "token": "uuid", "cliente": {"primeiro_nome": "Maria"}, "produto": "iPhone 13",
  "pagamento_online": true, "encerrado": false,
  "resumo": {"total": "300.00", "total_pago": "0.00", "parcelas_total": 3, "parcelas_pagas": 0,
             "parcelas_atrasadas": 1, "em_confirmacao": 0},
  "quitacao": {"total_restante": "300.00", "porcentagem_desconto": "10.00", "valor_desconto": "30.00",
               "total_com_desconto": "270.00", "pode_pagar_online": true, "opcoes": [{"forma": "pix", "...": "..."}],
               "pix_estatico": null, "pode_informar": true},
  "cobrancas_agrupadas_pendentes": [{"...cobrança de tipo parcelas ou quitacao..."}],
  "parcelas": [{
    "id": 1, "numero": 1, "valor": "100.00", "valor_restante": "100.00", "vencimento": "2026-11-10",
    "data_pagamento": null, "situacao": "atrasada",
    "pode_pagar_online": true, "pode_informar": true,
    "cobranca_pendente": null, "comprovantes": ["<referencia de cobrança paga>"],
    "pix_estatico": null
  }]
}
```
- **`situacao`** pode ser `paga`, `em_confirmacao`, `atrasada`, `vence_hoje` ou `a_vencer`.
- **`pix_estatico`** só vem quando o pagamento online está desligado. É o Pix da chave da empresa, que precisa de "informar" e da conferência da equipe.
- **`quitacao`** vem `null` quando não há parcela em aberto. Os totais usam o saldo (`valor_restante`) das parcelas.
  - **Com o pagamento online ligado:** traz as `opcoes`, e a quitação é paga pelo PagBank com baixa automática.
  - **Com ele desligado:** traz o `pix_estatico` da chave da empresa (que pode vir `null` se a loja não tiver chave Pix), e o cliente precisa usar "informar".
- **`cobrancas_agrupadas_pendentes`** traz as cobranças pendentes e válidas de várias parcelas ou de quitação. O `cobranca_pendente` de cada parcela só mostra as cobranças daquela parcela sozinha. Os `comprovantes` da parcela incluem as cobranças agrupadas pagas.
- **`acerto_manual`** (backoffice) traz as divergências da baixa automática: valor pago a menor, excedente sobre o saldo da parcela ou outro pedido pago.

**Cobrança:**
```json
{"referencia": "uuid", "tipo": "parcela|parcelas|quitacao", "forma": "pix",
 "status": "pendente|paga|expirada|cancelada", "parcela_id": 1,
 "parcelas": [{"id": 1, "numero": 1, "valor": "100.00", "desconto": "0.00"}],
 "valor_parcela": "100.00", "taxa": "0.00", "valor_total": "100.00", "expira_em": "...", "paga_em": null,
 "pix_copia_cola": "...", "qr_code_base64": "...", "boleto_linha_digitavel": null, "boleto_pdf_url": null,
 "link_pagamento": null}
```
- **Cartão:** abrir o `link_pagamento` (checkout do PagBank). O retorno volta para `<app>/pagamento/<token>?cobranca=<referencia>`.
- **Pix:** mostrar o QR (`qr_code_base64` é um PNG em base64, sem o prefixo `data:`) e o copia-e-cola. Consultar a cobrança a cada 5 s até `status = paga`.

### Rotas do app do cliente (`vendas.ipix.mobconnects.com`)

- **`/consultar-pagamentos`:** consulta por CPF e data de nascimento.
- **`/pagamento/:token`:** detalhe e pagamento. Aceita:
  - `?parcela=<id>`: abre a parcela;
  - `?parcelas=<id>,<id>`: já seleciona várias parcelas;
  - `?quitacao=1`: abre a quitação;
  - `?cobranca=<referencia>`: mostra o resultado do cartão.

As páginas antigas do Django (`/pagamento/<token>/` e `/consultar-pagamentos/`) redirecionam para essas rotas, com 302, quando `redirecionar_paginas_antigas` está ligado.

## API do backoffice (`/api/bo/v1/cobrancas_online/`)

| Método | Caminho | Quem pode | O que faz |
|---|---|---|---|
| GET / PATCH | `configuracao/` | GET: analista ou admin; PATCH: admin | Configuração. Também traz `pagbank_configurado` e `ambiente` (somente leitura) |
| GET | `cobrancas/?status=&forma=&origem=&duplicado=1&busca=` | analista ou admin | Lista paginada |
| GET | `registros/?cobranca=&tipo=chamada\|notificacao` | admin | Requisições e respostas (homologação) |
| GET | `parcelas/<id>/cobrancas/` | analista ou admin | `{cobrancas, opcoes, link_cliente}` |
| POST | `parcelas/<id>/cobrancas/` `{forma}` | analista ou admin + `vendas.change_pagamento` | Gera a cobrança (origem backoffice) |
| GET | `pagamentos/<id>/cobrancas/` | analista ou admin | `{cobrancas, quitacao: {tipo, valor, desconto, parcelas, opcoes} \| null, link_cliente}` |
| POST | `pagamentos/<id>/cobrancas/` `{forma, parcelas: [ids]}` ou `{forma, quitacao: true}` | analista ou admin + `vendas.change_pagamento` | Gera a cobrança agrupada |
| GET | `pagamentos/<id>/opcoes/?parcelas=1,2` ou `?quitacao=1` | analista ou admin | Valores e opções antes de gerar |
| POST | `parcelas/<id>/enviar-link/` | analista ou admin | Manda o link no WhatsApp. Responde 422 se a janela de 24h estiver fechada |

A cobrança serializada no backoffice traz:
- `tipo`, `tipo_rotulo` e `rotulo` (ex.: "Parcelas 1 e 2" ou "Quitação");
- `itens`: `[{parcela_id, numero, valor, desconto}]`;
- `qr_code_base64`: PNG em base64, sem o prefixo `data:`. Só vem no Pix pendente.

`parcelas/<id>/cobrancas/` também lista as cobranças agrupadas que incluem a parcela.

**Baixa manual:** `PATCH /api/bo/v1/financeiro/parcelas/<id>/` aceita `origem_baixa`. O `ParcelaSerializer` devolve `origem_baixa`.

## Assistente do WhatsApp

A ferramenta `gerar_link_pagamento` recebe uma destas entradas:
- `parcela_id`: uma parcela;
- `parcela_ids`: várias parcelas da mesma compra;
- `quitacao: true` mais um `parcela_id` da compra: a quitação.

`simular_quitacao` devolve o `parcela_id_para_quitar` de cada compra.

A ferramenta também aceita `forma`:
- **`link` (padrão):** a página do app, onde o cliente escolhe a forma de pagamento.
- **`pix`:** gera o Pix no PagBank. **O copia-e-cola é enviado pelo sistema** numa mensagem separada, depois da resposta, e o modelo nunca escreve o código.

O host do app do cliente entra na lista de links que o assistente pode enviar.
