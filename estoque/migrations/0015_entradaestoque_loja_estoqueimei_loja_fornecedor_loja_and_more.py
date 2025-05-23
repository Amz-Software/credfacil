# Generated by Django 4.2.16 on 2024-12-29 13:57

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0019_caixa_loja_cliente_loja_comprovantescliente_loja_and_more'),
        ('estoque', '0014_estoque_loja_alter_estoque_unique_together'),
    ]

    operations = [
        migrations.AddField(
            model_name='entradaestoque',
            name='loja',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='estoqueimei',
            name='loja',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='fornecedor',
            name='loja',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='produtoentrada',
            name='loja',
            field=models.ForeignKey(default=1, editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
            preserve_default=False,
        ),
    ]
