from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0156_comprovanteparcela'),
    ]

    operations = [
        migrations.AddField(
            model_name='analisecreditocliente',
            name='segunda_compra',
            field=models.BooleanField(default=False, verbose_name='É a segunda compra do cliente conosco'),
        ),
        migrations.AddField(
            model_name='historicalanalisecreditocliente',
            name='segunda_compra',
            field=models.BooleanField(default=False, verbose_name='É a segunda compra do cliente conosco'),
        ),
    ]
