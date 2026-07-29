from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0150_alter_loja_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='analisecreditocliente',
            name='imei_ultimos_digitos_vendedor',
            field=models.CharField(blank=True, max_length=4, null=True, verbose_name='Últimos 4 dígitos do IMEI (vendedor)'),
        ),
        migrations.AddField(
            model_name='historicalanalisecreditocliente',
            name='imei_ultimos_digitos_vendedor',
            field=models.CharField(blank=True, max_length=4, null=True, verbose_name='Últimos 4 dígitos do IMEI (vendedor)'),
        ),
    ]
