# Contrato da API — Administração (`/api/bo/v1/administracao/`)

Sessão do backoffice + CSRF (`X-CSRFToken`) em toda mutação. Cabeçalho opcional `X-Loja: <id>|todas`
(loja fora do escopo → 403). Erros `{"erro": {"codigo", "mensagem", "campos"}}`. Listas paginadas
`{count, page, page_size, total_pages, results}`. Método sem rota (inclusive GET em ação) → 405 `metodo_nao_permitido`.
PUT não existe: use PATCH. Troca da própria senha: `POST /api/bo/v1/me/senha/` (fora deste módulo).

## Regras de segurança (valem para usuários e grupos)
1. `is_superuser` e `is_staff` **nunca** são gravados (são só leitura; se vierem no corpo, são ignorados).
2. **Só concede o que possui:** grupos e permissões diretas só entram se estiverem contidos nas permissões efetivas
   de quem edita (superusuário pode tudo). Vale também para `backoffice_api.acessar_backoffice`.
   Violação → 403 `proibido` com `campos.grupos` e/ou `campos.permissoes`.
3. **Não altera quem tem mais acesso:** editar, desativar, reativar ou redefinir senha exige que o alvo não seja
   você mesmo, não seja superusuário nem staff (se você não for) e tenha permissões contidas nas suas (lidas do banco,
   mesmo com o alvo inativo). Violação → 403 `proibido` com a mensagem do motivo. O detalhe traz `pode_editar` e
   `motivo_bloqueio_edicao` para a tela desabilitar as ações.
4. **Escopo de lojas:** a lista mostra usuários vinculados (usuário, gerente ou loja principal) às lojas da requisição;
   acesso global (`vendas.can_view_all_stores`/superusuário) sem `X-Loja` vê todos, inclusive quem não tem loja.
   Superusuários só aparecem para superusuário. Usuário fora do escopo → 404.
   Vínculos com lojas só com lojas do seu escopo (403 `campos.lojas|lojas_gerenciadas|loja_principal`); os vínculos
   atuais fora do seu escopo são preservados e não aparecem para você.

---

## Usuários

### `GET usuarios/` — `accounts.view_user`
Query: `busca` (usuário, nome, sobrenome, e-mail), `grupo` (id), `loja` (id), `ativo` (`sim|nao|todos`, padrão `sim`),
`ordenar` (`usuario|nome|email|ultimo_acesso|criado_em`). Você mesmo não aparece na lista.
```json
{"results": [{"id": 5, "usuario": "ana.souza", "nome_completo": "Ana Souza", "email": "ana@ex.com", "ativo": true,
  "grupos": ["ANALISTA"], "loja_principal": {"id": 3, "nome": "Loja Centro"}, "ultimo_acesso": "2026-11-20T14:03:00-03:00"}]}
```

### `GET usuarios/{id}/` — `accounts.view_user`
```json
{"id": 5, "usuario": "ana.souza", "nome": "Ana", "sobrenome": "Souza", "nome_completo": "Ana Souza",
 "email": "ana@ex.com", "ativo": true, "superusuario": false, "staff": false,
 "ultimo_acesso": "...", "criado_em": "...",
 "grupos": [{"id": 2, "nome": "ANALISTA"}],
 "permissoes": [{"id": 88, "codigo": "vendas.view_cliente", "nome": "Ver cliente"}],
 "loja_principal": {"id": 3, "nome": "Loja Centro"},
 "lojas": [{"id": 3, "nome": "Loja Centro"}], "lojas_gerenciadas": [],
 "acesso_backoffice": true, "pode_editar": true, "motivo_bloqueio_edicao": null}
```
`permissoes` = permissões **diretas**; `acesso_backoffice` considera diretas + grupos.

### `POST usuarios/` — `accounts.add_user`
```json
{"usuario": "joao.silva", "nome": "João", "sobrenome": "Silva", "email": "joao@ex.com", "senha": "Senha@Forte2026",
 "grupos": [2], "permissoes": [88], "lojas": [3], "lojas_gerenciadas": [], "loja_principal": 3}
```
- `email` e `senha` obrigatórios; `usuario` opcional (sem ele, gera `nome.sobrenome` sem acentos, com sufixo numérico
  se já existir; nesse caso nome e sobrenome são obrigatórios).
- Senha validada pela política (`validate_password`: ≥ 10, maiúscula, minúscula, número, símbolo) → 400 `campos.senha`.
- `usuario` e `email` únicos (sem diferenciar maiúsculas) → 400 `campos.usuario|email`. E-mail gravado em minúsculas.
- Quem não tem acesso global precisa vincular ao menos uma loja → 400 `campos.lojas`.
- 201 = detalhe. Auditado (`usuario_criado`).

### `PATCH usuarios/{id}/` — `accounts.change_user`
Mesmos campos do POST (sem `senha`), todos opcionais. Listas (`grupos`, `permissoes`, `lojas`, `lojas_gerenciadas`)
substituem as atuais (salvo os vínculos de loja fora do seu escopo, preservados). 200 = detalhe.
Auditado (`usuario_alterado`, `dados` = `{campo: {"antes", "depois"}}`).

### `POST usuarios/{id}/desativar/` · `POST usuarios/{id}/reativar/` — `accounts.delete_user`
Corpo opcional `{"motivo": "Desligado"}`. Desativar = `is_active=false` (a sessão dele deixa de valer).
Idempotente. Auditado (`usuario_desativado`/`usuario_reativado`). 200 = detalhe.

### `POST usuarios/{id}/redefinir-senha/` — `accounts.change_user`
Corpo opcional `{"motivo": "..."}`. Gera senha temporária forte (16 caracteres), exibida **uma única vez**
(`Cache-Control: no-store`); as sessões abertas do usuário caem. Auditado (`senha_redefinida`, sem a senha).
`{"senha_temporaria": "k7#Qp...", "mensagem": "Anote e entregue a senha ao usuário: ela não será exibida de novo."}`

---

## Grupos (sem exclusão)

### `GET grupos/` — `auth.view_group`
Query: `busca` (nome), `ordenar` (`nome|total_usuarios|total_permissoes`).
`{"results": [{"id": 2, "nome": "ANALISTA", "total_permissoes": 31, "total_usuarios": 4, "pode_editar": true}]}`
`pode_editar` = as permissões do grupo estão contidas nas suas.

### `GET grupos/{id}/` — `auth.view_group`
Item da lista + `permissoes`: `[{"id", "codigo", "codename", "nome", "nome_original", "app_label", "app_nome",
"modelo", "modelo_nome", "acao"}]`.

### `POST grupos/` — `auth.add_group` · `PATCH grupos/{id}/` — `auth.change_group`
`{"nome": "Atendimento", "permissoes": [88, 91]}` (`permissoes` substitui a lista inteira).
Nome único → 400 `campos.nome`; permissão que você não possui → 403 `campos.permissoes`;
editar grupo com permissões que você não possui → 403. Auditado (`grupo_criado`, `grupo_alterado` com
`nome`, `permissoes_adicionadas`, `permissoes_removidas`). 201/200 = detalhe.

---

## Permissões

### `GET permissoes/` — `auth.view_permission`
Query: `busca` (nome, codename, app), `app` (app_label exato), `ordenar` (`app|modelo|codename`). Paginada; item igual
ao de `grupos/{id}/permissoes`.

### `GET permissoes/matriz/` — qualquer de `auth.view_permission`, `auth.view_group`, `auth.add_group`, `auth.change_group`, `accounts.add_user`, `accounts.change_user`
Para montar os checkboxes de grupos e permissões diretas. Sem paginação.
```json
{"apps": [{"app_label": "produtos", "nome": "Produtos", "modelos": [
  {"modelo": "marca", "nome": "Marca", "permissoes": [
    {"id": 41, "codigo": "produtos.view_marca", "codename": "view_marca", "nome": "Ver Marca", "acao": "view", "pode_conceder": true},
    {"id": 38, "codigo": "produtos.add_marca", "codename": "add_marca", "nome": "Adicionar Marca", "acao": "add", "pode_conceder": false}]}]}]}
```
Rótulos: permissões padrão viram `Ver|Adicionar|Alterar|Excluir <verbose_name do modelo>`; customizadas mantêm o
`name` com o prefixo inglês traduzido. `acao` é `view|add|change|delete` ou `null` (customizada); ordem: ver,
adicionar, alterar, excluir, depois as customizadas. `pode_conceder=false` → desabilitar o checkbox.

---

## Auditoria

### `GET auditoria/` — `backoffice_api.ver_auditoria`
Query: `usuario` (id), `acao`, `objeto_tipo` (ex.: `accounts.user`), `objeto_id`, `data_inicio`, `data_fim`
(`AAAA-MM-DD`, inclusivas, fuso local), `busca` (usuário, ação, descrição, motivo), `ordenar`
(`criado_em|acao|usuario_nome`; padrão `-criado_em`).
```json
{"results": [{"id": 120, "criado_em": "...", "usuario": 5, "usuario_nome": "ana.souza", "acao": "usuario_desativado",
  "objeto_tipo": "accounts.user", "objeto_id": "9", "descricao": "Usuário joao.silva", "motivo": "Desligado",
  "dados": {}, "ip": "200.1.2.3", "user_agent": "Mozilla/5.0 ..."}]}
```
Erro: 400 `campos.data_inicio|data_fim` (formato).

### `GET auditoria/acoes/` — `backoffice_api.ver_auditoria`
`{"acoes": ["login", "login_falhou", "usuario_criado", "..."]}` (para o filtro).

---

## Meu perfil

### `GET perfil/` · `PATCH perfil/` — qualquer usuário do backoffice (só os próprios dados)
`{"id": 5, "usuario": "ana.souza", "nome": "Ana", "sobrenome": "Souza", "email": "ana@ex.com"}`
PATCH aceita `nome`, `sobrenome`, `email`; **trocar o e-mail exige `senha_atual`** (400 `campos.senha_atual`).
E-mail único → 400 `campos.email`. Auditado (`perfil_alterado`, com antes/depois).

---

## Busca global (provedor do Ctrl+K)

### `GET busca/?termo=ana` — `accounts.view_user`
Usuários do seu escopo (mesma regra da lista) por nome, usuário ou e-mail; até 8, ativos primeiro.
Termo com menos de 2 caracteres → `{"resultados": []}`.
`{"resultados": [{"id": 5, "tipo": "usuario", "titulo": "Ana Souza", "subtitulo": "ana.souza · ana@ex.com", "ativo": true}]}`
Rota sugerida na SPA: `/administracao/usuarios/{id}`.
