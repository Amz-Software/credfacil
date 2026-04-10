from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0138_numeroautenticador_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='analisecreditocliente',
            name='codigo_reserva',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Código de Reserva'),
        ),
    ]
