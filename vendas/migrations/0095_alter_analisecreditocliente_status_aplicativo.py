# Generated by Django 4.2.16 on 2025-05-18 14:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0094_loja_codigo_aplicativo_loja_qr_code_aplicativo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analisecreditocliente',
            name='status_aplicativo',
            field=models.CharField(blank=True, choices=[('P', 'Pendente'), ('C', 'Confirmação pendente'), ('I', 'Instalado')], default='P', max_length=20, null=True, verbose_name='Status do aplicativo'),
        ),
    ]
