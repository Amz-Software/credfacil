"""Modelos da API do backoffice."""
from django.conf import settings
from django.db import models


class RegistroAuditoria(models.Model):
    """Quem fez o quê, quando e de onde, nas ações sensíveis do backoffice."""

    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='registros_auditoria',
    )
    # Guardado à parte para o registro continuar legível se o usuário sumir.
    usuario_nome = models.CharField(max_length=150, blank=True)
    acao = models.CharField(max_length=80, db_index=True)
    objeto_tipo = models.CharField(max_length=80, blank=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    descricao = models.CharField(max_length=255, blank=True)
    motivo = models.TextField(blank=True)
    dados = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'registro de auditoria'
        verbose_name_plural = 'registros de auditoria'
        indexes = [models.Index(fields=['objeto_tipo', 'objeto_id'])]
        permissions = [
            ('acessar_backoffice', 'Pode entrar no backoffice'),
            ('ver_auditoria', 'Pode consultar a trilha de auditoria'),
        ]

    def __str__(self) -> str:
        return f'{self.criado_em:%d/%m/%Y %H:%M} {self.usuario_nome} {self.acao}'
