from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0142_alter_venda_status_contrato'),
    ]

    operations = [
        migrations.AddField(
            model_name='comprovantescliente',
            name='consulta_serasa_2',
            field=models.FileField(blank=True, null=True, upload_to='comprovantes_clientes'),
        ),
        migrations.AddField(
            model_name='comprovantescliente',
            name='consulta_serasa_2_analise',
            field=models.BooleanField(default=False),
        ),
    ]
