# Generated by Django 4.2.16 on 2025-05-23 01:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0100_alter_comprovantescliente_restricao'),
    ]

    operations = [
        migrations.AlterField(
            model_name='comprovantescliente',
            name='restricao',
            field=models.BooleanField(default=False),
        ),
    ]
