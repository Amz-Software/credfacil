# Generated by Django 4.2.16 on 2025-04-21 14:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0043_analisecreditocliente_data_aprovacao_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analisecreditocliente',
            name='status',
            field=models.CharField(choices=[('EA', 'Em análise'), ('A', 'Aprovado'), ('R', 'Reprovado')], max_length=20),
        ),
    ]
