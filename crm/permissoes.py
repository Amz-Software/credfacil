"""Permissões do CRM. Só `crm.acessar_crm` libera ver o CRM; `gerenciar` exige as duas."""
from django.contrib.auth import get_user_model
from django.db.models import Q

PERM_ACESSAR = 'crm.acessar_crm'
PERM_GERENCIAR = 'crm.gerenciar_crm'


def pode_acessar(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.has_perm(PERM_ACESSAR))


def pode_gerenciar(user) -> bool:
    return pode_acessar(user) and user.has_perm(PERM_GERENCIAR)


def usuarios_com_acesso():
    """Usuários ativos que atendem no CRM (permissão direta, por grupo ou superusuário)."""
    filtro = (
        Q(is_superuser=True)
        | Q(user_permissions__codename='acessar_crm', user_permissions__content_type__app_label='crm')
        | Q(groups__permissions__codename='acessar_crm', groups__permissions__content_type__app_label='crm')
    )
    return get_user_model().objects.filter(filtro, is_active=True).distinct()

