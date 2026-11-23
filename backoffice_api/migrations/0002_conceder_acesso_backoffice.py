"""Concede `acessar_backoffice` aos grupos internos.

ANALISTA, ADMINISTRADOR e SUPERADMIN recebem a permissão, assim como os grupos
que já acessam o CRM (atendentes). VENDEDOR nunca recebe: vendedores usam só a
SPA de vendas. Outros grupos devem ser liberados pelo administrador.
"""
from django.db import migrations

GRUPOS_INTERNOS = ('ANALISTA', 'ADMINISTRADOR', 'SUPERADMIN')
GRUPO_VENDEDOR = 'VENDEDOR'


def conceder(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    app_config = apps.get_app_config('backoffice_api')
    app_config.models_module = True
    create_permissions(app_config, apps=apps, verbosity=0)

    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    permissao = Permission.objects.get(
        codename='acessar_backoffice', content_type__app_label='backoffice_api'
    )
    grupos = set(Group.objects.filter(name__in=GRUPOS_INTERNOS))
    grupos |= set(
        Group.objects.filter(
            permissions__codename='acessar_crm', permissions__content_type__app_label='crm'
        )
    )
    for grupo in grupos:
        if grupo.name != GRUPO_VENDEDOR:
            grupo.permissions.add(permissao)


def revogar(apps, schema_editor):
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(
        codename='acessar_backoffice', content_type__app_label='backoffice_api'
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('backoffice_api', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('crm', '0001_initial'),
    ]

    operations = [migrations.RunPython(conceder, revogar)]
