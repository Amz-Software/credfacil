from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0149_alter_venda_caixa'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='loja',
            options={
                'ordering': ['nome'],
                'permissions': (('can_view_all_stores', 'Pode ver todas as lojas'),),
                'verbose_name_plural': 'Lojas',
            },
        ),
    ]
