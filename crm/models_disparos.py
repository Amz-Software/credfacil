"""Disparo manual de cobrança (Central de cobrança): um template aprovado para um público filtrado.

O público é congelado na prévia (`ItemDisparo`, um por cliente): o que a prévia mostrou é
exatamente o que a rotina processa, item a item, conferindo de novo cada regra na hora do envio.
Cada envio que sai vira também uma `TentativaContato` (tipo DISPARO, sequência = id do disparo):
o histórico de contatos, a regra de "um aviso por dia" e a marcação de resposta valem igual.
"""
from django.conf import settings
from django.db import models


class DisparoCobranca(models.Model):
    class Status(models.TextChoices):
        PREVIA = 'PREVIA', 'Prévia'
        AGENDADO = 'AGENDADO', 'Agendado'
        ENVIANDO = 'ENVIANDO', 'Enviando'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'
        CANCELADO = 'CANCELADO', 'Cancelado'
        PAUSADO = 'PAUSADO', 'Pausado'

    EM_ANDAMENTO = (Status.AGENDADO, Status.ENVIANDO)
    CANCELAVEIS = (Status.PREVIA, Status.AGENDADO, Status.ENVIANDO, Status.PAUSADO)

    modelo = models.ForeignKey('crm.ModeloAbertura', on_delete=models.PROTECT, related_name='disparos')
    versao = models.ForeignKey('crm.VersaoAbertura', on_delete=models.PROTECT, related_name='disparos')
    filtros = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREVIA, db_index=True)
    total = models.PositiveIntegerField(default=0, help_text='Destinatários previstos na prévia.')
    excluidos = models.PositiveIntegerField(default=0, help_text='Fora do público na prévia, com o motivo.')
    enviados = models.PositiveIntegerField(default=0)
    falhas = models.PositiveIntegerField(default=0)
    ignorados = models.PositiveIntegerField(default=0, help_text='Deixaram de valer entre a prévia e o envio.')
    falhas_seguidas = models.PositiveSmallIntegerField(default=0)
    motivo_pausa = models.CharField(max_length=255, blank=True, default='')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    confirmado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='+')
    confirmado_em = models.DateTimeField(null=True, blank=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True)
    cancelado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='+')
    cancelado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-criado_em', '-id']
        default_permissions = ()

    def __str__(self) -> str:
        return f'Disparo #{self.pk} ({self.get_status_display()})'


class ItemDisparo(models.Model):
    """Um destinatário (ou um excluído, com o motivo) de um disparo."""

    class Situacao(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Na fila'
        ENVIADO = 'ENVIADO', 'Enviado'
        IGNORADO = 'IGNORADO', 'Ignorado no envio'
        FALHOU = 'FALHOU', 'Recusado pela Meta'
        EXCLUIDO = 'EXCLUIDO', 'Fora do público'

    disparo = models.ForeignKey(DisparoCobranca, on_delete=models.CASCADE, related_name='itens')
    cliente = models.ForeignKey('vendas.Cliente', on_delete=models.CASCADE, related_name='+')
    parcela = models.ForeignKey('vendas.Parcela', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    ordem = models.PositiveIntegerField()
    situacao = models.CharField(max_length=9, choices=Situacao.choices, default=Situacao.PENDENTE)
    motivo = models.CharField(max_length=30, blank=True, default='')
    tentativa = models.OneToOneField('crm.TentativaContato', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='item_disparo')
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['disparo', 'ordem']
        default_permissions = ()
        indexes = [models.Index(fields=['disparo', 'situacao', 'ordem'])]
