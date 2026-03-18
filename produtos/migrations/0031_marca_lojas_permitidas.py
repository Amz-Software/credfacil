from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('produtos', '0030_parcelamento_porcentagem_desconto'),
        ('vendas', '0137_alter_analisecreditocliente_numero_parcelas'),
    ]

    operations = [
        migrations.AddField(
            model_name='marca',
            name='lojas_permitidas',
            field=models.ManyToManyField(
                blank=True,
                help_text='Selecione as lojas que podem ver esta marca. Se nenhuma for selecionada, a marca ficará visível para todas as lojas.',
                related_name='marcas_permitidas',
                to='vendas.loja',
                verbose_name='Lojas Permitidas',
            ),
        ),
    ]
