from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0139_analisecreditocliente_codigo_reserva'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analisecreditocliente',
            name='codigo_reserva',
            field=models.ImageField(blank=True, null=True, upload_to='codigo_reserva/', verbose_name='Código de Reserva'),
        ),
    ]
