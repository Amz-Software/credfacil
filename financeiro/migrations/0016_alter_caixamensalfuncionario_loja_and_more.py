# Generated by Django 4.2.16 on 2025-01-06 23:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0026_alter_caixa_loja_alter_cliente_loja_and_more'),
        ('financeiro', '0015_alter_caixamensalfuncionario_loja_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='caixamensalfuncionario',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='caixamensalgastofixo',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='funcionario',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='gastofixo',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='gastosaleatorios',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
    ]
