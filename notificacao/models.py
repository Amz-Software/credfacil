from django.conf import settings
from django.db import models


class AssinaturaPush(models.Model):
    """Navegador/celular do usuário inscrito no Web Push (avisos com a tela do sistema fechada).

    Cada aparelho tem um `endpoint` próprio do serviço de push do navegador; o mesmo
    usuário pode ter vários (celular e computador). Endpoint recusado pelo serviço
    (404/410) é apagado no envio.
    """

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assinaturas_push')
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=300, blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Assinatura de push'
        verbose_name_plural = 'Assinaturas de push'

    def __str__(self) -> str:
        return f'{self.usuario} · {self.user_agent[:40] or self.endpoint[:40]}'
