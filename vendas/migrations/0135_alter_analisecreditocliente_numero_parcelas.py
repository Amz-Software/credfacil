from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0134_rename_produtos_permitidos_para_bloqueados'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analisecreditocliente',
            name='numero_parcelas',
            field=models.CharField(
                choices=[
                    ('4', '4x'),
                    ('6', '6x'),
                    ('8', '8x'),
                    ('10', '10x'),
                    ('12', '12x'),
                    ('14', '14x'),
                ],
                max_length=20,
            ),
        ),
    ]
