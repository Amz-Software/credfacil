from django.db import migrations, models


STATUS_ANALISE_CONCLUIDA = 'ANALISE_CONCLUIDA'


def definir_status_vendas_antigas(apps, schema_editor):
    Venda = apps.get_model('vendas', 'Venda')
    Venda.objects.filter(status_contrato__isnull=True).update(status_contrato=STATUS_ANALISE_CONCLUIDA)
    Venda.objects.filter(status_contrato='').update(status_contrato=STATUS_ANALISE_CONCLUIDA)


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0140_alter_analisecreditocliente_codigo_reserva'),
    ]

    operations = [
        migrations.AddField(
            model_name='venda',
            name='contrato_publico_uuid',
            field=models.UUIDField(blank=True, editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='venda',
            name='status_contrato',
            field=models.CharField(
                choices=[
                    ('ANALISE_CONCLUIDA', 'Analise concluida'),
                    ('AGUARDANDO_ASSINATURA', 'Aguardando assinatura'),
                    ('ENVIADO_AGUARDANDO_ANALISE', 'Enviado aguardando analise'),
                ],
                default='ANALISE_CONCLUIDA',
                max_length=40,
            ),
        ),
        migrations.RunPython(definir_status_vendas_antigas, migrations.RunPython.noop),
    ]
