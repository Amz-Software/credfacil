# `acessos` (permissões) — uso no Lovable

Este documento descreve o novo campo `acessos` adicionado à serialização da `Loja` (GET /api/lojas/{id}/) e como o frontend Lovable deve consumi-lo.

O backend agora inclui, junto aos dados da loja, um objeto `acessos` com booleans indicando se o usuário autenticado tem permissão para executar ações específicas. Exemplo:

```
{
  "acessos": {
    "pode_editar_loja": true,
    "pode_criar_loja": false,
    "pode_deletar_loja": false,
    "pode_criar_repasse": true,
    "pode_ver_repasse": true,
    "can_view_all_stores": false,
    "pode_criar_produto": true,
    "pode_editar_produto": true,
    "pode_deletar_produto": false,
    "pode_criar_solicitacao": true,
    "pode_criar_venda": true
  }
}
```

Chaves e mapeamento

- `pode_editar_loja`: `user.has_perm('vendas.change_loja')`
- `pode_criar_loja`: `user.has_perm('vendas.add_loja')`
- `pode_deletar_loja`: `user.has_perm('vendas.delete_loja')`
- `pode_criar_repasse`: `user.has_perm('financeiro.add_repasse')`
- `pode_ver_repasse`: `user.has_perm('financeiro.view_repasse')`
- `can_view_all_stores`: `user.has_perm('vendas.can_view_all_stores')`
- `pode_criar_produto`: `user.has_perm('produtos.add_produto')`
- `pode_editar_produto`: `user.has_perm('produtos.change_produto')`
- `pode_deletar_produto`: `user.has_perm('produtos.delete_produto')`
- `pode_criar_solicitacao`: `user.has_perm('vendas.add_cliente') OR user.has_perm('vendas.add_analisecreditocliente')`
- `pode_criar_venda`: `user.has_perm('vendas.add_venda')`

Como usar no Lovable (exemplo com Zustand)

- Ao selecionar/alterar a loja, o frontend deve chamar `GET /api/lojas/{id}/` e guardar o objeto `acessos` no store (ex: `lojaAcessos`).
- Use as flags para habilitar/ocultar botões e ações nas várias telas (lojas, produtos, solicitações, vendas).

Exemplo básico (fetch + atualização do estado):

```javascript
// pseudo-codigo
async function selecionarLoja(id) {
  const res = await fetch(`/api/lojas/${id}/`, { credentials: 'include' });
  const data = await res.json();
  lojaStore.setLoja(data); // inclui data.acessos
  lojaStore.setAcessos(data.acessos);
}
```

Recomendações

- Centralize lógica de permissões em um único store (ex: `lojaAcessos`) para evitar duplicação.
- Sempre consulte a flag antes de mostrar botões sensíveis (ex: se `pode_deletar_loja` for false, esconder botão "Excluir").
- Em ações que exigem segurança extra (deletar, criar), sempre validar no backend também (não confiar apenas no frontend).
- Para transições UX, ao tentar uma ação sem permissão, exibir uma mensagem clara: "Você não tem permissão para executar esta ação.".

Observações finais

- As permissões retornadas são calculadas no backend usando `request.user.has_perm(...)`. Alterações nos grupos/permissões do usuário no Django Admin refletirão imediatamente no retorno.
- Se precisar de permissões adicionais, informe os codenames desejados e eu adiciono ao retorno.
