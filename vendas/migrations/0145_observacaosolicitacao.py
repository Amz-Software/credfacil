from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('vendas', '0144_consultaserasaacesso'),
    ]

    operations = [
        migrations.CreateModel(
            name='ObservacaoSolicitacao',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('texto', models.TextField(verbose_name='Observação')),
                ('criado_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('analise_credito', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='observacoes', to='vendas.analisecreditocliente')),
                ('autor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='observacoes_solicitacao', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Observação da Solicitação',
                'verbose_name_plural': 'Observações das Solicitações',
                'ordering': ['-criado_em'],
            },
        ),
    ]
