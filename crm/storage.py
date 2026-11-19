"""Storage privado da mídia do CRM.

Com S3 (USE_S3) usa o storage padrão, que já é um bucket privado com URL assinada.
Sem S3, grava fora do MEDIA_ROOT (que o Django serve publicamente em /mediafiles/),
em CRM_MIDIA_ROOT, sem URL pública: o acesso é só pela rota assinada do CRM.
"""
from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage


class MidiaPrivadaStorage(FileSystemStorage):
    """Diretório lido das settings a cada uso (não fica preso no import) e sem URL pública."""

    def __init__(self):
        super().__init__()

    @property
    def base_location(self):
        return settings.CRM_MIDIA_ROOT

    @property
    def location(self):
        import os
        return os.path.abspath(self.base_location)

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise ValueError('A mídia do CRM é privada: use a URL assinada do CRM.')

    def deconstruct(self):
        return ('crm.storage.MidiaPrivadaStorage', (), {})


def midia_storage():
    if getattr(settings, 'USE_S3', False):
        return default_storage
    return MidiaPrivadaStorage()
