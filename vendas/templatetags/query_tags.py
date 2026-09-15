"""Tags de manipulação da query string das listagens."""

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def querystring_sem(context, *chaves) -> str:
    """Query string atual sem as chaves informadas, já com o `&` inicial.

    Serve para montar links que preservam os filtros da listagem, por exemplo
    `?page=2{% querystring_sem 'page' %}`. Diferente de `request.GET.items`,
    preserva chaves repetidas — sem isso um filtro múltiplo como
    `?loja=1&loja=2` perderia valores ao paginar.
    """
    request = context.get('request')
    if request is None:
        return ''

    params = request.GET.copy()
    for chave in chaves:
        params.pop(chave, None)

    codificado = params.urlencode()
    return f'&{codificado}' if codificado else ''
