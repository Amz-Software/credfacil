# Generated by Django 4.2.16 on 2025-05-01 16:43

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0054_alter_analisecreditocliente_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analisecreditocliente',
            name='cliente',
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='analises_credito', to='vendas.cliente'),
        ),
    ]
