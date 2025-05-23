# Generated by Django 4.2.16 on 2025-01-06 23:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0025_alter_contatoadicional_contato_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='caixa',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='cliente',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='comprovantescliente',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='contatoadicional',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='endereco',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='loja',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='pagamento',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='parcela',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='tipoentrega',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='tipopagamento',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='tipovenda',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
        migrations.AlterField(
            model_name='venda',
            name='loja',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja'),
        ),
    ]
