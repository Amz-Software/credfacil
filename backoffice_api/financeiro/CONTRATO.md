# Contrato — `/api/bo/v1/financeiro/` (contas a receber)

Sessão do backoffice + `X-CSRFToken` em toda mutação. Cabeçalho opcional `X-Loja: <id>|todas`.
Escopo: `Pagamento.loja`; `vendas.can_view_all_payments` (ou `can_view_all_stores`/superusuário) libera todas as lojas.
Objeto fora do escopo → **404**. Método não suportado → **405**. Erros no formato
`{"erro": {"codigo", "mensagem", "campos"}}` (400 `validacao`, 403 `proibido`, 404 `nao_encontrado`,
422 `regra_de_negocio`). Valores monetários são strings decimais; datas ISO 8601.
"Analista/admin" = grupo `ANALISTA` ou `ADMINISTRADOR` (superusuário passa em tudo).

## Situações de cobrança (chaves usadas em todo o módulo)
| chave | rótulo |
|---|---|
| `lembrete` | Lembrete |
| `bo` | BO |
| `flag_atrasado` | Cobrança |
| `sem_conexao` | Desabilitado |
| `roubo` | Roubo |
| `sem_contato` | Sem contato |
| `mais_prazo` | Mais prazo |
| `bloqueado` | Bloquear aparelho |
| `desativado` | Desativar cliente |
| `devolucao` | Devolução |

`estado` (lista e detalhe), primeira condição verdadeira: `desativado`, `devolucao`, `bloqueado`, `sem_contato`,
`mais_prazo`, `atrasado`, `pendente` ("A vencer"), `pago`, `quitado`, `sem_situacao`. Vem com `estado_rotulo`.

---

## GET `contas-a-receber/`
Permissão: `vendas.view_pagamento`. Paginado (`page`, `page_size` ≤ 100).
Só pagamentos parcelados (sem ENTRADA/caixa) de vendas não canceladas.

| Parâmetro | Descrição |
|---|---|
| `busca` | nome, CPF (com ou sem máscara), observação de contato ou nº do pagamento |
| `status` | `no_prazo` (≥1 parcela paga) · `atrasado` · `quitado` · `pendente` (a vencer) |
| `loja` | id; **só com `vendas.can_view_all_stores`** (senão 403) |
| `status_pagamento` | id, repetível (OU) |
| `situacao` | chave de situação ou `pagamento_efetuado`, repetível (E) |
| `ordenar` | `criado_em` (padrão `-criado_em`), `id`, `valor`, `cliente`, `proximo_vencimento`; `-` = desc. |

```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [{
  "id": 12, "valor": "300.00", "quantidade_parcelas": 3, "quitado": false, "venda_id": 8,
  "cliente": {"id": 5, "nome": "Maria", "cpf": "***.456.789-**", "telefone": "91999999999", "telefone_secundario": ""},
  "loja": {"id": 1, "nome": "Loja A"},
  "produto": {"id": 3, "nome": "Galaxy A15", "imei": "3500..."},
  "estado": "atrasado", "estado_rotulo": "Atrasado",
  "situacoes": {"lembrete": false, "bo": false, "flag_atrasado": true, "sem_conexao": false, "roubo": false,
                "sem_contato": false, "mais_prazo": false, "bloqueado": false, "desativado": false, "devolucao": false},
  "status_pagamento": [{"id": 2, "nome": "Acordo", "cor_hex": "#FFAA00"}],
  "valores": {"valor_atrasado": "200.00", "ultimo_vencimento_atrasado": "2026-11-14",
              "valor_pago_ultimo": "0.00", "ultimo_pagamento": null,
              "valor_a_vencer": "100.00", "proximo_vencimento": "2026-12-14",
              "valor_total_parcelas": "300.00", "valor_quitado": "0.00",
              "parcelas_pagas": 0, "parcelas_totais": 3,
              "situacao_parcela_aberta": "atrasado"}
}]}
```
`situacao_parcela_aberta`: `em_dia` | `atrasado` | `pago_parcialmente`. Erros: 400 (filtro inválido, com `campos`), 403.

## GET `status-pagamento/`
Permissão: `vendas.view_pagamento`. Lista simples (sem paginação): `[{"id", "nome", "cor_hex"}]`.

## GET `contas-a-receber/{id}/`
Permissão: analista/admin + `vendas.view_pagamento`. CPF completo.
```json
{"id": 12, "valor": "300.00", "quantidade_parcelas": 3, "data_primeira_parcela": "2026-10-14",
 "porcentagem_desconto": "10.00", "quitado": false,
 "tipo_pagamento": {"id": 2, "nome": "IPX"}, "loja": {"id": 1, "nome": "Loja A"},
 "venda": {"id": 8, "data_venda": "2026-10-01T10:00:00-03:00", "is_deleted": false, "status_contrato": "ASSINADO",
           "produto": {"id": 3, "nome": "Galaxy A15", "imei": "3500..."}},
 "cliente": {"id": 5, "nome": "Maria", "cpf": "12345678901", "email": null, "telefone": "...", "telefone_secundario": "",
             "nascimento": "1990-01-01", "rg": "...", "cep": "...", "endereco": "...", "bairro": "...", "cidade": "...",
             "informacao_pessoal": {"nome": "...", "contato": "...", "endereco": "...", "obteve_contato": false},
             "contato_adicional": null},
 "estado": "atrasado", "estado_rotulo": "Atrasado",
 "situacoes": [{"chave": "lembrete", "rotulo": "Lembrete", "ativo": false}, "..."],
 "status_pagamento": [{"id": 2, "nome": "Acordo", "cor_hex": "#FFAA00", "ativo": true}],
 "totais": {"valor": "300.00", "total_pago": "0.00", "valor_pendente": "300.00", "parcelas_pagas": 0,
            "parcelas_totais": 3, "total_valor_original": "300.00", "total_valor_pago": "0.00", "aguardando_quitacao": 0},
 "pode_gerar_bo": true,
 "parcelas": [{"id": 40, "pagamento_id": 12, "numero_parcela": 1, "valor": "100.00", "valor_pago": "0.00",
               "desconto": "0.00", "valor_restante": "100.00", "data_vencimento": "2026-10-14", "data_pagamento": null,
               "pago": false, "pagamento_efetuado": false, "pagamento_efetuado_em": null, "atrasada": true,
               "modificado_em": "...", "modificado_por": "Ana",
               "comprovantes": [{"id": 7, "parcela_id": 40, "nome_arquivo": "pix.pdf", "extensao": "pdf",
                                 "is_imagem": false, "is_pdf": true, "observacao": "", "criado_em": "...",
                                 "criado_por": "Ana", "url_arquivo": "/api/bo/v1/financeiro/comprovantes/7/arquivo/"}]}],
 "contatos": [{"id": 3, "data": "2026-11-01", "observacao": "...", "criado_em": "...", "modificado_em": "...", "criado_por": "Ana"}],
 "historico": [{"data": "...", "usuario": "Ana", "objeto": "pagamento", "objeto_id": 12, "numero_parcela": null,
                "tipo": "alteracao", "alteracoes": [{"campo": "bloqueado", "rotulo": "bloqueado", "de": false, "para": true}]}]}
```
`historico`: versões do `simple_history` do pagamento e das parcelas (telas Django + API), 50 mais recentes.
`tipo`: `criacao` | `alteracao` | `remocao`. Erros: 403, 404.

## PATCH `contas-a-receber/{id}/` — desconto
Permissão: analista/admin + `vendas.change_pagamento`. Auditado (`pagamento_desconto_alterado`).
Corpo: `{"porcentagem_desconto": "12.50", "motivo": "opcional"}` (0 a 100; outros campos → 400).
Resposta: detalhe atualizado.

## POST `contas-a-receber/{id}/situacoes/`
Permissão: `vendas.change_pagamento`. Substitui os 11 toggles por GET. Auditado
(`pagamento_situacao_alterada` / `pagamento_status_alterado`, com antes/depois).
Corpo — exatamente um de `situacao`/`status_pagamento`; sem `ativo` alterna, com `ativo` define:
```json
{"situacao": "bloqueado", "ativo": true, "motivo": "opcional"}
{"status_pagamento": 2}
```
Resposta: detalhe atualizado. Erros: 400, 403, 404 (status inexistente ou conta fora do escopo).

## POST `contas-a-receber/{id}/quitar/`
Permissão: `vendas.can_confirm_quitacao`. Corpo: `{"motivo": "mín. 5 caracteres", "forcar": false}` (motivo obrigatório).
Aplica `porcentagem_desconto` às parcelas com `pagamento_efetuado` e não pagas (distribuição proporcional,
última parcela absorve o arredondamento), marca-as pagas com a data de hoje e o pagamento como `quitado`.
`forcar: true` (só ADMINISTRADOR/superusuário; senão 403) quita **todas** as parcelas em aberto, mesmo sem o
cliente ter informado o pagamento; a tela pede confirmação dupla.
Idempotente: conta já quitada e sem parcela a quitar devolve 200 com o detalhe, sem nova auditoria (repetição
depois de uma resposta perdida por timeout).
Auditado (`pagamento_quitado`, com os ajustes e `sem_informe_do_cliente`). Resposta: detalhe.
Erros: 400 (motivo), 403 (`forcar` sem ser admin), 422 (nenhuma parcela aguardando / em aberto).

## POST `contas-a-receber/{id}/parcelas/` — adicionar até 4
Permissão: analista/admin + `vendas.add_parcela`. Auditado (`parcelas_adicionadas`).
```json
{"parcelas": [{"data_vencimento": "2027-03-14"}, {}], "motivo": "opcional"}
```
`data_vencimento` omitida = 1 mês após a parcela anterior. As novas recebem os próximos números; o saldo
(`valor` do pagamento − total pago) é redistribuído entre todas as pendentes (existentes + novas).
Resposta **201** com o detalhe. Erros: 400 (`parcelas` vazia ou > 4), 422 (sem parcela e sem data).

## PATCH `parcelas/{id}/`
Permissão: analista/admin + `vendas.change_pagamento`; mudar `data_vencimento` exige também
`vendas.change_vencimento_parcela` (senão 403). Auditado (`parcela_editada`, antes/depois por campo).
Campos aceitos: `valor_pago` (≥ 0), `pago`, `data_pagamento` (ou null), `data_vencimento`, `motivo`.
Qualquer outro campo (ex.: `valor`) → 400 "Campo não editável". Resposta: a parcela (formato do detalhe).

## Comprovantes
- **POST `parcelas/{id}/comprovantes/`** (multipart: `arquivo`, `observacao` ≤ 255) — analista/admin +
  `vendas.change_pagamento`. PDF, JPG, JPEG, PNG, WEBP ou HEIC, até 10 MB, **conteúdo conferido pelos bytes**.
  Resposta 201: comprovante. Auditado (`comprovante_anexado`).
- **GET `comprovantes/{id}/arquivo/`** — analista/admin + `vendas.view_pagamento`. Entrega o arquivo
  (inline; `?download=1` força o download). Auditado (`comprovante_acessado`). 404 se o arquivo sumiu.
- **DELETE `comprovantes/{id}/`** — analista/admin + `vendas.change_pagamento`. 204. Auditado (`comprovante_removido`).

## Contatos de cobrança
- **POST `contas-a-receber/{id}/contatos/`** — `vendas.add_contato`. `{"data": "2026-11-20", "observacao": "..."}` → 201
  `{"id", "data", "observacao", "criado_em", "modificado_em", "criado_por"}`.
- **PATCH `contas-a-receber/{id}/contatos/{contato_id}/`** — `vendas.change_contato`. Campos parciais.
  Contato de outro cliente → 404.

### Ligado ao CRM (aba Contatos)
- **GET `contas-a-receber/{id}/contato-crm/`** — analista/admin + `vendas.view_pagamento`. Painel:
  `{"crm_disponivel", "status": {"codigo", "rotulo"} | null, "alerta", "telefones": [...], "conversa_id",
  "pode_anotar", "linha_do_tempo": [...], "opcoes": {"canais", "resultados_cliente", "resultados_referencia"}}`.
  A linha do tempo vem do mais novo para o mais antigo e junta `origem` `manual` (`Contato`, `somente_data`,
  `contato_id` editável), `tentativa` (`TentativaContato`: avisos da régua com `automatica` e `parcela`,
  ligações e tentativas da equipe, com `canal`, `numero`, `resultado`, `resultado_estado`) e `nota` (notas
  internas das conversas do cliente, sem automáticas e apagadas). Sem `crm.acessar_crm`: `crm_disponivel=false`,
  só os registros manuais, sem telefones. O GET sincroniza os telefones do cadastro (como o painel do CRM).
- **POST `contas-a-receber/{id}/tentativas/`** — acima + `crm.acessar_crm`.
  `{"telefone": <id de TelefoneCliente do cliente>, "canal": "LIGACAO"|"WHATSAPP", "resultado": "...",
  "observacao": "..."}` → 201 com o painel. Telefone de outro cliente → 400 (`campos.telefone`); resultado que
  não vale para o número (ex.: "Referência ajudou" em número do cliente) → 422.
- **POST `contas-a-receber/{id}/notas/`** — acima + `crm.acessar_crm`. `{"texto": "..."}` (até 2000) → 201 com o
  painel. A nota vai para a conversa do cliente com mensagem mais recente; sem conversa → 422.

## BO (notificação extrajudicial)
Permissão: analista/admin + `financeiro.add_notificacaobo`. Exige parcela vencida em aberto (senão **422**).
- **GET `contas-a-receber/{id}/bo/previa/`**
```json
{"pagamento_id": 12, "venda_id": 8,
 "cliente": {"nome": "Maria", "cpf_exibicao": "123.***.***-01", "telefone": "...", "telefone_secundario": "—", "endereco": "Rua A, Centro, Belém"},
 "loja": {"nome": "...", "cnpj": "...", "telefone": "...", "endereco": "...", "cidade": "—", "uf": "—"},
 "produto": {"nome": "...", "modelo": "...", "imei": "..."},
 "data_assinatura": "2026-10-01", "inicio_vigencia": "01/10/2026", "fim_vigencia": "14/12/2026",
 "valor_mensal": "100.00", "vencimento_primeira_atrasada": "2026-10-14",
 "local_assinatura": "Loja A, 23/11/2026", "referencias_padrao": "1. Mãe: 9199..."}
```
- **POST `contas-a-receber/{id}/bo/pdf/`** — `{"referencias_personais": "texto editado (vazio = padrão)"}` →
  `application/pdf` (inline). Auditado (`bo_gerado`).
