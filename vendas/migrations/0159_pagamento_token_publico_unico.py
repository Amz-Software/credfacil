"""Etapa 2 de 2: `Pagamento.token_publico` obrigatório, único e com default UUID4."""
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vendas', '0158_pagamento_token_publico'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pagamento',
            name='token_publico',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
