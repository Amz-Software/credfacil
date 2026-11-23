# Contrato — módulo `credito` (`/api/bo/v1/credito/`)

Fila de análise de crédito (solicitações) e pré-análise rápida. Tag OpenAPI: `bo-credito`.

Convenções gerais (núcleo): sessão do backoffice + `X-CSRFToken` nas mutações; `X-Loja: <id>|todas`;
erros `{"erro": {"codigo", "mensagem", "campos"}}`; listas `{count, page, page_size, total_pages, results}`
com `?page=` e `?page_size=` (máx. 100); dinheiro como string decimal (`"1200.00"`); datas ISO 8601.

**Id da solicitação = id do cliente** (o mesmo da API do vendedor e do `target_url` do WebSocket).
`analise_id` é o id da `AnaliseCreditoCliente`.

**Escopo de loja:** todas as lojas para superusuário, `vendas.can_view_all_stores` ou
`vendas.view_all_analise_credito`; senão as lojas do usuário (usuário, gerente ou `user.loja`).
Objeto fora do escopo → 404. Método sem rota (ex.: GET numa ação) → 405 antes da checagem de permissão.

Códigos de erro comuns: 400 `validacao` (com `campos`), 401 `nao_autenticado`, 403 `proibido`,
404 `nao_encontrado`, 405 `metodo_nao_permitido`, 422 `regra_de_negocio` (mensagem pronta do serviço).

---

## Solicitações

### `GET solicitacoes/` — fila
Permissão: `vendas.view_cliente`.

| Parâmetro | Valores |
|---|---|
| `busca` (ou `termo`) | nome ou CPF (com/sem máscara; CPF a partir de 3 dígitos) |
| `loja` | um ou mais ids (`?loja=1&loja=2` ou `?loja=1,2`), sempre dentro do escopo |
| `status` | `EA`, `A`, `R`, `C` |
| `status_app` | `P`, `C`, `I` |
| `data_inicio`, `data_fim` | `AAAA-MM-DD` (data da análise, dias inteiros) |
| `analise_online` | `1` / `0` |
| `vendas_nao_finalizadas` | `1` (sem venda gerada) |
| `ordenar` | `id`, `nome`, `data_analise`, `status`, `loja`, `produto` (prefixo `-`). Padrão: ordem de criação, da mais recente para a mais antiga (todos os status juntos) |

Só lista clientes que têm análise. Valor inválido → 400 com `campos.<parametro>`.

```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [{
  "id": 41, "analise_id": 37, "cliente": "Maria Silva", "cpf": "***.456.789-**",
  "loja": {"id": 2, "nome": "Loja A"}, "vendedor": {"id": 9, "nome": "Vendedor"},
  "produto": {"id": 5, "nome": "Galaxy", "is_iphone": false},
  "valor": "1200.00", "entrada": "200.00", "numero_parcelas": 10, "data_pagamento": "10",
  "status": "EA", "status_rotulo": "Em análise", "status_app": "P", "status_app_rotulo": "Pendente",
  "etapa": "aguardando_qr_code", "etapa_rotulo": "Aguardando QR code",
  "is_iphone": false, "icloud_configurado_vendedor": false, "icloud_confirmado_analista": false,
  "tem_imei": false, "analise_online": false, "segunda_compra": false,
  "venda_gerada": false, "venda_id": null,
  "criado_em": "2026-11-23T09:10:00-03:00", "tempo_espera_segundos": 1820
}]}
```
`etapa`: `finalizado`, `pronto_para_venda`, `aguardando_imei`, `aguardando_configuracao_inicial`,
`aguardando_confirmacao`, `aguardando_qr_code`, `pendente`. `tempo_espera_segundos` só em `EA`.

### `GET solicitacoes/kpis/`
Permissão: `vendas.view_cliente`. Parâmetro opcional `loja` (um ou mais). Respeita escopo/`X-Loja`.
```json
{"por_status": {"EA": 3, "A": 10, "R": 2, "C": 1}, "total": 16, "aprovadas_sem_venda": 4,
 "online": {"por_status": {"EA": 1, "A": 4, "R": 0, "C": 0}, "total": 5, "aprovadas_sem_venda": 2},
 "analise_rapida": {"por_status": {"EA": 0, "A": 3, "R": 0, "C": 0}, "total": 3, "aprovadas_sem_venda": 1},
 "status_opcoes": [{"codigo": "EA", "rotulo": "Em análise"}], "status_app_opcoes": [{"codigo": "P", "rotulo": "Pendente"}]}
```
`online` repete os contadores só para as análises com `analise_online = true`; `analise_rapida`, só para as solicitações cujo cliente foi gerado por uma `PreAnaliseRapida`.

### `GET solicitacoes/{id}/` — detalhe
Permissão: `vendas.view_cliente`. CPF completo.
```json
{
  "id": 41, "analise_id": 37,
  "cliente": {"nome": "...", "email": null, "telefone": "91999999999", "telefone_secundario": "", "cpf": "12345678901",
              "nascimento": "1990-01-01", "rg": "...", "cep": "...", "endereco": "...", "bairro": "...", "cidade": "...",
              "profissao": "...", "quantidade_dependentes": 0, "recebe_auxilio": false, "total_renda": "0.00",
              "observacao_cliente": ""},
  "loja": {"id": 2, "nome": "Loja A"},
  "contato_adicional": {"nome": "...", "contato": "...", "endereco": "...", "obteve_contato": false},
  "informacao_pessoal": {"nome": "...", "contato": "...", "endereco": "...", "obteve_contato": false},
  "comprovantes": {"restricao": false, "arquivos": [
      {"campo": "documento_identificacao_frente", "rotulo": "Documento de identificação (frente)", "presente": true,
       "url": "/api/bo/v1/credito/solicitacoes/41/arquivos/documento_identificacao_frente/", "analisado": false, "serasa": false}]},
  "analise": {"id": 37, "status": "EA", "status_rotulo": "Em análise", "status_app": "P", "status_app_rotulo": "Pendente",
              "etapa": "...", "etapa_rotulo": "...", "data_analise": "...", "data_aprovacao": null, "data_reprovacao": null,
              "data_cancelamento": null, "aprovado_por": null, "vendedor": {"id": 9, "nome": "..."},
              "analise_online": false, "segunda_compra": false, "observacao": null, "data_pagamento": "10",
              "numero_parcelas": 10, "entrada_informada": null, "entrada": "200.00",
              "produto": {"id": 5, "nome": "Galaxy", "is_iphone": false, "valor": "1200.00", "entrada_cliente": "200.00",
                          "marca": {"id": 1, "nome": "Samsung"}},
              "imei": null, "imei_informado": null, "imei_ultimos_digitos_vendedor": null,
              "numero_autenticador": null, "icloud": {"email": null, "configurado_vendedor": false, "confirmado_analista": false}},
  "parcelamento": {"valor_produto": "1200.00", "entrada_minima": "200.00", "numero_parcelas": 10,
                   "opcoes": [{"qtd_vezes": 10, "porcentagem_juros": "20.00", "porcentagem_desconto": "5.00", "entrada": "200.00",
                               "valor_financiado": "1000.00", "valor_total": "1200.00", "valor_parcela": "120.00",
                               "repasse_logista": "1000.00", "selecionada": true}],
                   "selecionada": {"...": "a opção escolhida"}, "erro": null},
  "venda": null,
  "linha_do_tempo": [{"tipo": "alteracao", "origem": "analise", "data": "...", "usuario": {"id": 3, "nome": "Analista"},
                      "titulo": "Status: Em análise → Aprovado",
                      "mudancas": [{"campo": "status", "rotulo": "Status", "de": "Em análise", "para": "Aprovado"}], "texto": null}],
  "acoes": {"editar": true, "aprovar": true, "reprovar": true, "cancelar": true, "observar": true, "alterar_status_app": true,
            "instalar_app": true, "confirmar_instalacao": false, "confirmar_icloud": false, "informar_imei": false,
            "gerar_venda": false, "ver_serasa": true},
  "edicao": {"pode_editar": true, "campos_editaveis": ["nome", "telefone", "..."]}
}
```
- Serasa (`consulta_serasa`, `consulta_serasa_2`, `restricao` e o histórico desses campos): só superusuário, grupo
  ANALISTA ou `vendas.view_consulta_serasa`. Sem acesso: os arquivos não aparecem e `restricao` é `null`.
- `numero_autenticador`: só ANALISTA/ADMINISTRADOR (senão `null`). A senha do iCloud nunca é exposta.
- `parcelamento` usa o mesmo cálculo da geração da venda (`calcular_valores_venda`). `erro` explica quando não há simulação.
- `linha_do_tempo`: histórico (simple_history) da análise, do cliente e dos comprovantes + observações; mais recente primeiro, até 200 eventos. `tipo`: `criacao`, `alteracao`, `observacao`.
- `acoes` é só conforto para a interface; cada endpoint confere de novo.

### `PATCH solicitacoes/{id}/` — edição
Permissão: `vendas.change_cliente`. JSON ou multipart (arquivos). **Envie só os campos alterados**; o resto fica como está.
Depois da venda gerada só ANALISTA/ADMINISTRADOR ou `vendas.can_edit_finished_sale` (senão 403).

Campos aceitos (os mesmos dos forms de `vendas/forms.py`; o que o usuário pode alterar agora está em `edicao.campos_editaveis`):
- cliente: `nome, telefone, telefone_secundario, cpf, nascimento, rg, cep, endereco, bairro, cidade, profissao, quantidade_dependentes, recebe_auxilio, total_renda`
- contato adicional: `nome_adicional, contato, endereco_adicional, obteve_contato`
- informação pessoal: `nome_pessoal, contato_pessoal, endereco_pessoal, obteve_contato_pessoal`
- comprovantes (multipart): `documento_identificacao_frente, documento_identificacao_verso, comprovante_residencia, foto_cliente, consulta_serasa, consulta_serasa_2` + `*_analise` (booleanos) e `restricao`
- análise: `produto, data_pagamento ("1"|"10"|"20"), numero_parcelas, entrada_informada, analise_online, segunda_compra, numero_autenticador`

Regras: validações dos forms; contatos adicional/pessoal não podem ser iguais; ao menos um contato completo;
parcelamento precisa existir para a marca (se produto/parcelas mudarem); depois da venda gerada `produto`,
`data_pagamento`, `numero_parcelas` e `entrada_informada` ficam travados para todos. Arquivos: PDF, JPG, PNG ou WEBP
(tipo conferido pelo conteúdo), até 10 MB. Campo que o usuário não pode alterar → 400 com
`campos.<campo> = ["Você não pode alterar este campo."]`. Chaves desconhecidas são ignoradas.

Resposta 200: o detalhe + `"aviso"` (texto quando há outras solicitações com o mesmo CPF/RG/nome/telefone, senão `null`).
Auditoria: `solicitacao_editada` com a lista de campos alterados.

### `GET solicitacoes/{id}/arquivos/{campo}/`
Permissão: `vendas.view_cliente` (+ regra do Serasa para `consulta_serasa*`, senão 403). `campo`:
`documento_identificacao_frente, documento_identificacao_verso, comprovante_residencia, foto_cliente, consulta_serasa, consulta_serasa_2, codigo_reserva`.
Entrega o arquivo (PDF/imagem inline; `?download=1` força o download; outros tipos como `application/octet-stream`).
Arquivo ausente → 404. Todo acesso grava `documento_acessado`; Serasa também grava `ConsultaSerasaAcesso`.

### `GET solicitacoes/{id}/qr-instalacao/`
Permissão: `vendas.change_cliente`.
```json
{"qr_instalacao": "data:image/png;base64,...", "codigo_instalacao": "AB12CD34EF56GH78",
 "qr_aplicativo": "data:image/png;base64,... | null", "codigo_aplicativo": "... | null"}
```
`qr_aplicativo`/`codigo_aplicativo` vêm da loja CredFacil (o mesmo QR do modal "instalar app" da tela atual).

### `GET solicitacoes/{id}/opcoes-edicao/`
Permissão: `vendas.change_cliente`. Opções dos selects do formulário de edição, lidas dos mesmos forms do PATCH.
```json
{"produtos": [{"id": 5, "nome": "Galaxy (Samsung) - Entrada: R$ 200,00", "marca_id": 1, "is_iphone": false,
               "valor": "1200.00", "entrada_cliente": "200.00"}],
 "parcelas_por_marca": {"1": [10, 12]},
 "data_pagamento": [{"codigo": "1", "rotulo": "Dia 1"}, {"codigo": "10", "rotulo": "Dia 10"}, {"codigo": "20", "rotulo": "Dia 20"}],
 "numeros_autenticadores": [{"id": 3, "numero": "91999990000", "descricao": "Chip 1"}]}
```
`produtos`: os permitidos para a loja da solicitação + o atual. `numeros_autenticadores`: ativos da loja; `null` para
quem não é ANALISTA/ADMINISTRADOR (o campo nem existe no form).

### Ações (POST)
Todas respondem `{"mensagem": "...", "solicitacao": <item da fila>}` (200), exceto quando indicado, e gravam auditoria.

| Caminho | Permissão | Corpo | Observações / auditoria |
|---|---|---|---|
| `{id}/aprovar/` | `change_status_analise` | — | 422 se já aprovada. `analise_aprovada` (status anterior/novo) |
| `{id}/reprovar/` | `change_status_analise` | `{"motivo"}` (mín. 5) | 422 se já reprovada. Cria observação "Motivo da reprovação: …". `analise_reprovada` com motivo |
| `{id}/cancelar/` | `change_analisecreditocliente` + `change_status_analise` | `{"motivo"}` | Só muda o status (como a tela; a venda gerada não é desfeita). Observação + `analise_cancelada` |
| `{id}/observacoes/` | superusuário ou grupo ANALISTA/ADMINISTRADOR/SUPERADMIN | `{"texto"}` | **201** `{"id", "texto", "autor", "criado_em"}`. `observacao_adicionada` |
| `{id}/status-app/` | `change_cliente` | `{"status_app": "P"\|"C"\|"I"}` | `status_app_alterado` |
| `{id}/instalar-app/` | `change_cliente` | — | Status do app → "Confirmação pendente". `instalacao_app_marcada` |
| `{id}/confirmar-instalacao/` | `change_status_analise` + grupo ANALISTA | — | 422 sem IMEI ou fora de "Confirmação pendente". `instalacao_app_confirmada` |
| `{id}/confirmar-icloud/` | `change_status_analise` + grupo ANALISTA | — | 422 se o vendedor não configurou. `icloud_confirmado` |
| `{id}/informar-imei/` | `change_analisecreditocliente` + grupo ANALISTA | `{"imei"}` | Usa o estoque da loja da solicitação (cria o IMEI se preciso); Android vira "Instalado". `imei_informado` |
| `{id}/gerar-venda/` | `vendas.add_venda` | — | **201** + `"venda_id"`. Mesmo serviço e travas da tela (`gerar_venda_da_analise`). `venda_gerada` (objeto = venda) |
| `{id}/log-consulta-serasa/` | `view_cliente` + regra do Serasa | `{"tipo": "serasa"\|"serasa_2"}` | **201** `{"id", "tipo", "aberto_em"}`. `consulta_serasa_aberta` |

Notificações e eventos de WebSocket saem dos signals existentes (`proposta_aceita`, `proposta_negada`,
`proposta_cancelada`, `instalacao_confirmada`...).

## Busca global

### `GET busca/?termo=`
Permissão: `vendas.view_cliente`. Até 8 solicitações do escopo (mais recentes primeiro); termo com menos de 2 caracteres → lista vazia.
```json
{"resultados": [{"id": 41, "cliente": "Maria Silva", "cpf": "***.456.789-**", "status": "EA", "status_rotulo": "Em análise", "loja": "Loja A"}]}
```

## Pré-análises rápidas

### `GET pre-analises/`
Permissão: `vendas.view_cliente`. Filtros: `busca` (nome/CPF), `status` (`P`, `A`, `R`), `loja`, `data_inicio`, `data_fim`
(data de envio), `finalizada` (`1`/`0`), `ordenar` (`id`, `criado_em`, `nome_completo`, `status`, `data_decisao`; padrão `-criado_em`).
```json
{"count": 1, "page": 1, "page_size": 25, "total_pages": 1, "results": [{
  "id": 7, "nome_completo": "João Souza", "cpf": "***.654.321-**", "loja": {"id": 2, "nome": "Loja A"},
  "status": "P", "status_rotulo": "Pendente", "finalizada": false, "cliente_gerado_id": null,
  "tem_consulta_serasa": false, "tem_comprovante_residencia": true, "possui_duas_referencias": true,
  "segunda_compra": false, "criado_por": {"id": 9, "nome": "..."}, "analisado_por": null,
  "data_decisao": null, "criado_em": "..."}]}
```

### `GET pre-analises/{id}/`
Item da lista com CPF completo e mais:
```json
{"observacao": null,
 "arquivos": [{"campo": "foto_rg_frente", "rotulo": "Foto do RG (frente)", "presente": true,
               "url": "/api/bo/v1/credito/pre-analises/7/arquivos/foto_rg_frente/", "analisado": null, "serasa": false}],
 "consulta_serasa": {"presente": false, "url": null, "anexada_por": null, "anexada_em": null},
 "acoes": {"aprovar": true, "reprovar": true, "gerenciar_serasa": true}}
```
`consulta_serasa` é `null` para quem não gerencia o Serasa (regra: superusuário, `change_status_analise`,
`view_consulta_serasa` ou grupo ANALISTA).

### Ações
| Caminho | Permissão | Corpo | Resposta / regras |
|---|---|---|---|
| `POST {id}/aprovar/` | `change_status_analise` | — | Detalhe. 422 se não estiver pendente. `pre_analise_aprovada` |
| `POST {id}/reprovar/` | `change_status_analise` | `{"motivo"}` (mín. 5) | Detalhe (`observacao` = motivo). 422 se não pendente. `pre_analise_reprovada` |
| `POST {id}/consulta-serasa/` | regra do Serasa | multipart `arquivo` (PDF/JPG/PNG/WEBP, ≤ 10 MB) | Detalhe. Substitui o anterior. 422 se já virou proposta. `pre_analise_serasa_anexada` |
| `DELETE {id}/consulta-serasa/` | regra do Serasa | — | Detalhe. 404 se não houver arquivo; 422 se já virou proposta. `pre_analise_serasa_removida` |

### `GET pre-analises/{id}/arquivos/{campo}/`
`campo`: `foto_rg_frente`, `foto_rg_verso`, `consulta_serasa` (este exige a regra do Serasa). Permissão `vendas.view_cliente`.
Auditado (`documento_acessado`).

### `GET pre-analises/relatorio.pdf`
Superusuário ou grupo ANALISTA/ADMINISTRADOR. Mesmos filtros da lista (e escopo). PDF (WeasyPrint) igual ao da tela atual,
como anexo. Auditado (`relatorio_pre_analises_gerado`, com filtros e total).
