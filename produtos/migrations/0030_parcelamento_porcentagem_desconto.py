from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0029_marca_ativo_alter_marca_icone'),
    ]

    operations = [
        migrations.AddField(
            model_name='parcelamento',
            name='porcentagem_desconto',
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=5, verbose_name='Porcentagem de desconto (%)'),
        ),
    ]
