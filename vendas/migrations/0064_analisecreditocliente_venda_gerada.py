# Generated by Django 4.2.16 on 2025-05-03 21:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0063_alter_analisecreditocliente_imei'),
    ]

    operations = [
        migrations.AddField(
            model_name='analisecreditocliente',
            name='venda_gerada',
            field=models.BooleanField(default=False),
        ),
    ]
