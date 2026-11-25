"""Ligações de voz pelo WhatsApp (Calling API da Cloud API).

O áudio vai direto entre o navegador de quem atende e a Meta (WebRTC); aqui fica só o
controle: quem ligou, quem atendeu, status, duração e o SDP da negociação.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Chamada(models.Model):
    class Direcao(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Recebida'
        SAIDA = 'SAIDA', 'Feita pela equipe'

    class Status(models.TextChoices):
        TOCANDO = 'TOCANDO', 'Tocando'            # recebida, esperando alguém atender
        CHAMANDO = 'CHAMANDO', 'Chamando'         # feita, esperando o cliente atender
        EM_ANDAMENTO = 'EM_ANDAMENTO', 'Em andamento'
        ENCERRADA = 'ENCERRADA', 'Encerrada'
        PERDIDA = 'PERDIDA', 'Não atendida'
        RECUSADA = 'RECUSADA', 'Recusada'
        FALHOU = 'FALHOU', 'Falhou'

    ATIVAS = (Status.TOCANDO, Status.CHAMANDO, Status.EM_ANDAMENTO)

    conversa = models.ForeignKey('crm.Conversa', on_delete=models.PROTECT, related_name='chamadas')
    wa_call_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    phone_number_id = models.CharField(max_length=32, blank=True, default='',
                                       help_text='Número da empresa que fez ou recebeu a ligação.')
    direcao = models.CharField(max_length=7, choices=Direcao.choices)
    status = models.CharField(max_length=12, choices=Status.choices, db_index=True)
    sdp_oferta = models.TextField(blank=True, default='', help_text='Oferta do cliente (ligação recebida).')
    sdp_resposta = models.TextField(blank=True, default='', help_text='Resposta do cliente (ligação feita).')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+', help_text='Quem atendeu ou quem ligou.')
    iniciada_em = models.DateTimeField(default=timezone.now, db_index=True)
    atendida_em = models.DateTimeField(null=True, blank=True)
    encerrada_em = models.DateTimeField(null=True, blank=True)
    duracao_s = models.PositiveIntegerField(null=True, blank=True)
    erro = models.TextField(blank=True, default='')
    mensagem = models.ForeignKey('crm.Mensagem', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                 help_text='Registro da ligação na conversa.')

    class Meta:
        ordering = ['-iniciada_em', '-id']
        default_permissions = ()

    def __str__(self) -> str:
        return f'{self.get_direcao_display()} {self.get_status_display()} #{self.pk}'

    @property
    def ativa(self) -> bool:
        return self.status in self.ATIVAS
