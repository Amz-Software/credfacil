# Generated by Django 4.2.16 on 2024-12-15 19:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0013_loja_usuarios'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pagamento',
            name='parcelas',
            field=models.PositiveIntegerField(blank=True, default=1, null=True),
        ),
    ]
