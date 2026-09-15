"""Verificações de acesso baseadas em papéis (grupos) do backoffice.

Centraliza a regra de "quem é ANALISTA ou ADMINISTRADOR" para que views,
mixins e templates compartilhem a mesma definição.
"""

from django.contrib.auth.mixins import UserPassesTestMixin

ROLE_ANALISTA = 'ANALISTA'
ROLE_ADMINISTRADOR = 'ADMINISTRADOR'
ROLES_ANALISTA_ADMIN = (ROLE_ADMINISTRADOR, ROLE_ANALISTA)


def user_is_analista_or_admin(user):
    """True para superusuários e para membros dos grupos ANALISTA/ADMINISTRADOR."""
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return user.groups.filter(name__in=ROLES_ANALISTA_ADMIN).exists()


class AnalistaOuAdminRequiredMixin(UserPassesTestMixin):
    """Restringe a view a superusuários, ANALISTA e ADMINISTRADOR."""

    def test_func(self):
        return user_is_analista_or_admin(self.request.user)
