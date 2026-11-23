"""Rótulos legíveis em português das permissões e matriz app → modelo → permissões."""
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils.text import capfirst

ACOES_PADRAO = {'view': 'Ver', 'add': 'Adicionar', 'change': 'Alterar', 'delete': 'Excluir'}
ORDEM_ACOES = {acao: indice for indice, acao in enumerate(ACOES_PADRAO)}
PREFIXOS_INGLES = (
    ('Can view all ', 'Ver todos: '),
    ('Can view own ', 'Ver o próprio: '),
    ('Can add ', 'Adicionar '),
    ('Can change ', 'Alterar '),
    ('Can delete ', 'Excluir '),
    ('Can view ', 'Ver '),
)


def nome_do_app(app_label: str) -> str:
    try:
        return capfirst(str(apps.get_app_config(app_label).verbose_name))
    except LookupError:
        return capfirst(app_label)


def nome_do_modelo(content_type: ContentType) -> str:
    modelo = content_type.model_class()
    if modelo is None:
        return capfirst(content_type.model)
    return capfirst(str(modelo._meta.verbose_name))


def acao_padrao(permissao) -> str | None:
    """'view'/'add'/'change'/'delete' se for permissão padrão do modelo; senão None."""
    acao, _, modelo = permissao.codename.partition('_')
    if acao in ACOES_PADRAO and modelo == permissao.content_type.model:
        return acao
    return None


def rotulo_permissao(permissao) -> str:
    """'Can add venda' → 'Adicionar Venda' (verbose_name do modelo); customizadas: traduz o prefixo."""
    acao = acao_padrao(permissao)
    if acao:
        modelo = permissao.content_type.model_class()
        nome = str(modelo._meta.verbose_name) if modelo else permissao.content_type.model
        return f'{ACOES_PADRAO[acao]} {nome}'
    for ingles, portugues in PREFIXOS_INGLES:
        if permissao.name.startswith(ingles):
            return portugues + permissao.name[len(ingles):]
    return permissao.name


def _ordem_permissao(permissao) -> tuple:
    acao = acao_padrao(permissao)
    return (ORDEM_ACOES.get(acao, len(ORDEM_ACOES)), rotulo_permissao(permissao).lower())


def matriz_permissoes(permissoes, *, concediveis: set[str] | None) -> list[dict]:
    """Permissões agrupadas por app e modelo; `concediveis=None` = pode conceder todas."""
    por_app: dict[str, dict[int, list]] = {}
    tipos: dict[int, ContentType] = {}
    for permissao in permissoes.select_related('content_type'):
        tipo = permissao.content_type
        tipos[tipo.pk] = tipo
        por_app.setdefault(tipo.app_label, {}).setdefault(tipo.pk, []).append(permissao)

    resultado = []
    for app_label in sorted(por_app, key=lambda rotulo: nome_do_app(rotulo).lower()):
        modelos = []
        for tipo_id, lista in por_app[app_label].items():
            tipo = tipos[tipo_id]
            modelos.append({
                'modelo': tipo.model,
                'nome': nome_do_modelo(tipo),
                'permissoes': [_item(p, concediveis) for p in sorted(lista, key=_ordem_permissao)],
            })
        modelos.sort(key=lambda m: m['nome'].lower())
        resultado.append({'app_label': app_label, 'nome': nome_do_app(app_label), 'modelos': modelos})
    return resultado


def _item(permissao, concediveis: set[str] | None) -> dict:
    codigo = f'{permissao.content_type.app_label}.{permissao.codename}'
    return {
        'id': permissao.pk,
        'codigo': codigo,
        'codename': permissao.codename,
        'nome': rotulo_permissao(permissao),
        'acao': acao_padrao(permissao),
        'pode_conceder': concediveis is None or codigo in concediveis,
    }
