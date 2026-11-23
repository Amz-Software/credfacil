"""Regras de conta compartilhadas entre as telas Django e a API."""
from django.db.models import Q

from accounts.models import User


def lojas_para_login(username: str) -> list[dict]:
    """Lojas (id, nome) do usuário pelo username ou e-mail, para a tela de login.

    Considera só vínculos explícitos (usuário ou gerente da loja); o FK legado
    `user.loja` não concede acesso por si só. Usuário inexistente devolve lista
    vazia, igual a um usuário sem loja: a busca não revela quem tem conta.
    """
    user = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).order_by('pk').first()
    if user is None:
        return []
    lojas = (user.lojas.all() | user.lojas_gerenciadas.all()).distinct().order_by('nome')
    return [{'id': loja.id, 'nome': loja.nome} for loja in lojas]
