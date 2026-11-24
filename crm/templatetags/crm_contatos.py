"""Card "Telefones e tentativas" do painel da conversa (um por cliente vinculado)."""
from django import template

from crm.web.contatos import dados_do_cliente

register = template.Library()


@register.inclusion_tag('crm/parciais/contatos_cliente.html', takes_context=True)
def contatos_do_cliente(context, cliente_id: int) -> dict:
    from vendas.models import Cliente

    cliente = (Cliente.objects.select_related('contato_adicional', 'informacao_pessoal')
               .filter(pk=cliente_id).first())
    return {
        'contatos': dados_do_cliente(cliente) if cliente else None,
        'conversa': context.get('conversa'),
        'url_da_conversa': context.get('url_da_conversa', ''),
        'csrf_token': context.get('csrf_token'),
    }
