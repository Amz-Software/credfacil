"""Etapa 1 de 2: cria `Pagamento.token_publico` (nulo) e preenche os registros existentes.

Cada pagamento recebe um UUID4 próprio. Um `AddField` com `default=uuid.uuid4`
avaliaria o default uma única vez e repetiria o mesmo valor em todas as linhas;
por isso o campo nasce nulo, é preenchido aqui e só fica único na 0159.
"""
import uuid

from django.db import migrations, models

TAMANHO_DO_LOTE = 500


def preencher_tokens(apps, schema_editor):
    Pagamento = apps.get_model('vendas', 'Pagamento')
    pendentes = Pagamento.objects.filter(token_publico__isnull=True).only('pk')
    lote = []
    for pagamento in pendentes.iterator(chunk_size=TAMANHO_DO_LOTE):
        pagamento.token_publico = uuid.uuid4()
        lote.append(pagamento)
        if len(lote) >= TAMANHO_DO_LOTE:
            Pagamento.objects.bulk_update(lote, ['token_publico'])
            lote = []
    if lote:
        Pagamento.objects.bulk_update(lote, ['token_publico'])


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0157_analisecreditocliente_segunda_compra_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pagamento',
            name='token_publico',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(preencher_tokens, migrations.RunPython.noop),
    ]
