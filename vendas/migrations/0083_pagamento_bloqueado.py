# Generated by Django 4.2.16 on 2025-05-09 22:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0082_alter_loja_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagamento',
            name='bloqueado',
            field=models.BooleanField(default=False),
        ),
    ]
