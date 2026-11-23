"""Bases dos serializers do CRM: nome do componente no OpenAPI com prefixo `Crm`.

Evita colisão com serializers homônimos de outros módulos (`Cliente`, `Mensagem`, `Nota`...)
no esquema que a SPA usa para gerar os tipos (`CrmMensagem`, `CrmConversaItem`...).
"""
from rest_framework import serializers

PREFIXO = 'Crm'
SUFIXO = 'Serializer'


class _ComponenteCrm:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        meta = getattr(cls, 'Meta', None)
        nome = PREFIXO + cls.__name__.removesuffix(SUFIXO)
        cls.Meta = type('Meta', (meta,) if meta else (), {'ref_name': nome})


class CrmSerializer(_ComponenteCrm, serializers.Serializer):
    pass


class CrmModelSerializer(_ComponenteCrm, serializers.ModelSerializer):
    pass
