# Generated by Django 4.2.16 on 2025-05-24 14:50

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0103_loja_porcentagem_desconto_4_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='loja',
            name='porcentagem_desconto',
        ),
    ]
