import uuid
from datetime import timedelta

from django.db import models
from django.utils import timezone


class FotoSession(models.Model):
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    foto = models.ImageField(upload_to='foto_sessions/', null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    expira_em = models.DateTimeField()

    class Meta:
        verbose_name = 'Sessão de Foto'
        verbose_name_plural = 'Sessões de Foto'

    def save(self, *args, **kwargs):
        if not self.pk and not self.expira_em:
            self.expira_em = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def expirada(self):
        return timezone.now() > self.expira_em

    def __str__(self):
        return str(self.session_id)
