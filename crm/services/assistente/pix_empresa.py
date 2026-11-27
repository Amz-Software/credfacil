"""Chave PIX da empresa (CNPJ da loja IPX) e link onde o próprio cliente consulta as parcelas.

A chave vem do cadastro (Loja com credfacil=True, a mesma da página pública de pagamento),
nunca do modelo. Vai numa mensagem separada, só a chave, para o cliente copiar fácil.
"""
from crm.models import ConfiguracaoCRM

CAMINHO_CONSULTA = 'consultar-pagamentos/'


def chave() -> str:
    from vendas.models import Loja

    loja = Loja.objects.filter(credfacil=True).order_by('pk').first()
    return (loja.chave_pix or '').strip() if loja else ''


def link_consulta() -> str:
    """Página pública: o cliente digita CPF e nascimento e vê as parcelas (vai ao app se configurado)."""
    base = ConfiguracaoCRM.obter().url_publica.strip().rstrip('/')
    return f'{base}/{CAMINHO_CONSULTA}' if base else ''
