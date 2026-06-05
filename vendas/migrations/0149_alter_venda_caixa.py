from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0148_historicalcomprovantescliente_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='venda',
            name='caixa',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='vendas',
                to='vendas.caixa',
            ),
        ),
    ]
