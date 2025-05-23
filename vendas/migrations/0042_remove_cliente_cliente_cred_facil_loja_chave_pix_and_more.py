# Generated by Django 4.2.16 on 2025-04-21 14:15

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0014_tipoproduto_assistencia'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('vendas', '0041_alter_venda_options'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='cliente',
            name='cliente_cred_facil',
        ),
        migrations.AddField(
            model_name='loja',
            name='chave_pix',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='cliente',
            name='bairro',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='cep',
            field=models.CharField(default='', max_length=8),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='cidade',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='comprovantes',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.PROTECT, related_name='comprovantes_clientes', to='vendas.comprovantescliente'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='endereco',
            field=models.CharField(default='', max_length=200),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='rg',
            field=models.CharField(default='', max_length=20),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='telefone',
            field=models.CharField(default=231, max_length=20),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='cliente',
            name='uf',
            field=models.CharField(default='', max_length=2),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='comprovantescliente',
            name='comprovante_residencia',
            field=models.ImageField(default='', upload_to='comprovantes_clientes/%Y/%m/%d/'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='comprovantescliente',
            name='consulta_serasa',
            field=models.ImageField(default='', upload_to='comprovantes_clientes/%Y/%m/%d/'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='comprovantescliente',
            name='documento_identificacao_frente',
            field=models.ImageField(default='', upload_to='comprovantes_clientes/%Y/%m/%d/'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='comprovantescliente',
            name='documento_identificacao_verso',
            field=models.ImageField(default='', upload_to='comprovantes_clientes/%Y/%m/%d/'),
            preserve_default=False,
        ),
        migrations.CreateModel(
            name='AnaliseCreditoCliente',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('modificado_em', models.DateTimeField(auto_now=True)),
                ('data_analise', models.DateField()),
                ('status', models.CharField(choices=[('Em análise', 'EA'), ('Aprovado', 'A'), ('Reprovado', 'Reprovado')], max_length=20)),
                ('observacao', models.TextField(blank=True, null=True)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='analises_credito', to='vendas.cliente')),
                ('criado_por', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_criadas', to=settings.AUTH_USER_MODEL)),
                ('loja', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_loja', to='vendas.loja')),
                ('modificado_por', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='%(class)s_modificadas', to=settings.AUTH_USER_MODEL)),
                ('produto', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='analises_credito', to='produtos.produto')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
