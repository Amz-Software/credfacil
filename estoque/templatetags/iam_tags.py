import re

from django import template
from produtos.models import Produto

register = template.Library()


@register.filter
def whatsapp_url(telefone):
    """Converte um número de telefone em um link do WhatsApp (https://wa.me/).

    Mantém apenas os dígitos e adiciona o código do país (55) quando o número
    está no formato local (DDD + número, 10 ou 11 dígitos). Retorna string
    vazia se não houver dígitos suficientes.
    """
    if not telefone:
        return ''
    digits = re.sub(r'\D', '', str(telefone))
    if len(digits) in (10, 11):
        digits = '55' + digits
    if len(digits) < 12:
        return ''
    return 'https://wa.me/' + digits

@register.filter
def has_perm(user, perm):
    return user.has_perm(perm)

register.filter('has_perm', has_perm)

@register.filter
def has_group(user, group_name):
    return user.groups.filter(name=group_name).exists()


@register.filter
def total_vendas(produto, loja_id):
    if loja_id:
        return produto.produto.total_vendas(loja_id=loja_id)
    return 0

@register.filter
def get_item(dict_, key):
    return dict_.get(key, 0)
