from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('vendas', '0143_comprovantescliente_consulta_serasa_2_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsultaSerasaAcesso',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('serasa', 'Consulta Serasa'), ('serasa_2', 'Consulta Serasa 2')], max_length=16)),
                ('aberto_em', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=512, null=True)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='consulta_serasa_acessos', to='vendas.cliente')),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consulta_serasa_acessos', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Acesso a Consulta Serasa',
                'verbose_name_plural': 'Acessos a Consultas Serasa',
                'ordering': ['-aberto_em'],
            },
        ),
        migrations.AddIndex(
            model_name='consultaserasaacesso',
            index=models.Index(fields=['cliente', 'tipo'], name='vendas_cons_cliente_idx'),
        ),
    ]
