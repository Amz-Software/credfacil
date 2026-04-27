from django.db import migrations, models


STATUS_AGUARDANDO_ASSINATURA = 'AGUARDANDO_ASSINATURA'
STATUS_ASSINADO = 'ASSINADO'
STATUS_ANALISE_CONCLUIDA = 'ANALISE_CONCLUIDA'
STATUS_ENVIADO_AGUARDANDO_ANALISE = 'ENVIADO_AGUARDANDO_ANALISE'


def migrar_status_contrato(apps, schema_editor):
    Venda = apps.get_model('vendas', 'Venda')
    Venda.objects.filter(status_contrato__in=[STATUS_ANALISE_CONCLUIDA, STATUS_ENVIADO_AGUARDANDO_ANALISE]).update(
        status_contrato=STATUS_ASSINADO
    )
    Venda.objects.filter(status_contrato__isnull=True).update(status_contrato=STATUS_AGUARDANDO_ASSINATURA)
    Venda.objects.filter(status_contrato='').update(status_contrato=STATUS_AGUARDANDO_ASSINATURA)


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0141_venda_contrato_publico_status'),
    ]

    operations = [
        migrations.RunPython(migrar_status_contrato, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='venda',
            name='status_contrato',
            field=models.CharField(
                choices=[
                    ('AGUARDANDO_ASSINATURA', 'Aguardando assinatura'),
                    ('ASSINADO', 'Assinado'),
                ],
                default='AGUARDANDO_ASSINATURA',
                max_length=40,
            ),
        ),
    ]
