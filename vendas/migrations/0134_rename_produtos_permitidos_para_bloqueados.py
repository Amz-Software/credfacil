from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0133_loja_produtos_permitidos'),
    ]

    operations = [
        migrations.RenameField(
            model_name='loja',
            old_name='produtos_permitidos',
            new_name='produtos_bloqueados',
        ),
        migrations.AlterField(
            model_name='loja',
            name='produtos_bloqueados',
            field=models.ManyToManyField(
                blank=True,
                related_name='lojas_bloqueadas',
                to='produtos.produto',
            ),
        ),
    ]
