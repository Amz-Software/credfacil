"""Cadastros do CRM: etiquetas, respostas rápidas e mensagens de abertura (templates da Meta)."""
from django.conf import settings
from django.db import models


class Etiqueta(models.Model):
    class Cor(models.TextChoices):
        CINZA = 'CINZA', 'Cinza'
        VERMELHO = 'VERMELHO', 'Vermelho'
        LARANJA = 'LARANJA', 'Laranja'
        AMARELO = 'AMARELO', 'Amarelo'
        VERDE = 'VERDE', 'Verde'
        AZUL = 'AZUL', 'Azul'
        ROXO = 'ROXO', 'Roxo'
        ROSA = 'ROSA', 'Rosa'

    nome = models.CharField(max_length=40, unique=True)
    cor = models.CharField(max_length=8, choices=Cor.choices, default=Cor.CINZA)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['ordem', 'nome']
        default_permissions = ()

    def __str__(self) -> str:
        return self.nome


class RespostaRapida(models.Model):
    atalho = models.SlugField(max_length=40, unique=True)
    titulo = models.CharField(max_length=80)
    texto = models.TextField(max_length=4096)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['ordem', 'titulo']
        default_permissions = ()

    def __str__(self) -> str:
        return f'/{self.atalho}'


class ModeloAbertura(models.Model):
    """Mensagem de abertura: template da Meta criado pela tela. Não se exclui, só se desativa."""

    chave = models.SlugField(max_length=40, unique=True)
    titulo = models.CharField(max_length=60)
    ordem = models.PositiveSmallIntegerField(default=0)
    ativo = models.BooleanField(default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ordem', 'titulo']
        default_permissions = ()

    def __str__(self) -> str:
        return self.titulo


class VersaoAbertura(models.Model):
    """Cada texto enviado à Meta é um template novo, com nome nunca reaproveitado."""

    class Status(models.TextChoices):
        ENVIANDO = 'ENVIANDO', 'Enviando à Meta'
        EM_ANALISE = 'EM_ANALISE', 'Em análise na Meta'
        APROVADO = 'APROVADO', 'Aprovado'
        REJEITADO = 'REJEITADO', 'Rejeitado'
        PAUSADO = 'PAUSADO', 'Pausado'
        DESATIVADO = 'DESATIVADO', 'Desativado'
        ERRO_ENVIO = 'ERRO_ENVIO', 'Erro no envio'
        DESCARTADO = 'DESCARTADO', 'Descartado'

    modelo = models.ForeignKey(ModeloAbertura, on_delete=models.PROTECT, related_name='versoes')
    versao = models.PositiveSmallIntegerField()
    nome_meta = models.CharField(max_length=120, unique=True)
    corpo = models.TextField(max_length=1024)
    corpo_meta = models.TextField(max_length=1024)
    mapa_parametros = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ENVIANDO)
    categoria_meta = models.CharField(max_length=20, blank=True, default='')
    motivo = models.TextField(blank=True, default='')
    erro = models.TextField(blank=True, default='')
    meta_template_id = models.CharField(max_length=64, blank=True, default='')
    vigente = models.BooleanField(default=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_em = models.DateTimeField(null=True, blank=True)
    decidido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['modelo', '-versao']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['modelo', 'versao'], name='crm_versao_unica_por_modelo'),
        ]

    def __str__(self) -> str:
        return self.nome_meta
