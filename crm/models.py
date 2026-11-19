"""Modelos do CRM de WhatsApp (ver docs/CRM_WHATSAPP.md e arquitetura-bot-crm-whatsapp.md §4)."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from crm.models_cadastros import Etiqueta, ModeloAbertura, RespostaRapida, VersaoAbertura  # noqa: F401
from crm.telefone import formatar_telefone

JANELA_ATENDIMENTO = timedelta(hours=24)
LIMITE_TEXTO = 4096


class Conversa(models.Model):
    """Uma conversa por número de WhatsApp. Nunca é apagada."""

    class Modo(models.TextChoices):
        AUTOMATICO = 'AUTOMATICO', 'Atendimento automático'
        AGUARDANDO = 'AGUARDANDO', 'Aguardando a equipe'
        HUMANO = 'HUMANO', 'Com a equipe'

    class Situacao(models.TextChoices):
        ABERTA = 'ABERTA', 'Aberta'
        PENDENTE = 'PENDENTE', 'Pendente'
        RESOLVIDA = 'RESOLVIDA', 'Resolvida'

    telefone = models.CharField(max_length=20, unique=True)
    contato_nome = models.CharField(max_length=150, blank=True, default='')
    apelido = models.CharField(max_length=60, blank=True, default='')
    clientes = models.ManyToManyField('vendas.Cliente', blank=True, related_name='conversas_whatsapp')

    modo = models.CharField(max_length=12, choices=Modo.choices, default=Modo.AUTOMATICO, db_index=True)
    assumida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='conversas_crm',
    )
    assumida_em = models.DateTimeField(null=True, blank=True)
    aguardando_desde = models.DateTimeField(null=True, blank=True)

    situacao = models.CharField(max_length=10, choices=Situacao.choices, default=Situacao.ABERTA, db_index=True)
    situacao_em = models.DateTimeField(null=True, blank=True)
    resolvida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )

    ultima_mensagem_em = models.DateTimeField(null=True, blank=True, db_index=True)
    ultima_entrada_em = models.DateTimeField(null=True, blank=True)
    ultima_humana_em = models.DateTimeField(null=True, blank=True)
    boas_vindas_em = models.DateTimeField(null=True, blank=True)
    nao_lidas = models.PositiveIntegerField(default=0)

    processando = models.BooleanField(default=False)
    processando_desde = models.DateTimeField(null=True, blank=True)

    etiquetas = models.ManyToManyField(Etiqueta, blank=True, related_name='conversas')

    lembrete_em = models.DateTimeField(null=True, blank=True, db_index=True)
    lembrete_texto = models.CharField(max_length=200, blank=True, default='')
    lembrete_para = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    lembrete_criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    lembrete_avisado_em = models.DateTimeField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ultima_mensagem_em', '-id']
        default_permissions = ()
        permissions = [
            ('acessar_crm', 'Pode acessar o CRM de WhatsApp'),
            ('gerenciar_crm', 'Pode gerenciar o CRM de WhatsApp'),
        ]

    def __str__(self) -> str:
        return self.nome_exibicao

    def delete(self, *args, **kwargs):
        raise PermissionError('Conversas do WhatsApp não podem ser apagadas.')

    @property
    def nome_exibicao(self) -> str:
        return self.apelido or self.contato_nome or formatar_telefone(self.telefone)

    @property
    def primeiro_nome(self) -> str:
        nome = self.contato_nome or self.apelido
        return nome.split()[0] if nome else ''

    def janela_expira_em(self):
        if not self.ultima_entrada_em:
            return None
        return self.ultima_entrada_em + JANELA_ATENDIMENTO

    def janela_aberta(self, agora=None) -> bool:
        expira = self.janela_expira_em()
        return bool(expira and (agora or timezone.now()) < expira)


def _caminho_midia(pasta: str):
    def gerar(instance, filename: str) -> str:
        extensao = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'bin'
        conversa_id = instance.mensagem.conversa_id
        return f'whatsapp/{pasta}/{conversa_id}/{uuid.uuid4().hex}.{extensao}'
    return gerar


def caminho_arquivo(instance, filename):
    return _caminho_midia('conversas')(instance, filename)


def caminho_miniatura(instance, filename):
    return _caminho_midia('miniaturas')(instance, filename)


def caminho_envio(instance, filename):
    return _caminho_midia('envios')(instance, filename)


class Mensagem(models.Model):
    class Direcao(models.TextChoices):
        ENTRADA = 'ENTRADA', 'Recebida'
        SAIDA = 'SAIDA', 'Enviada'

    class Autor(models.TextChoices):
        CLIENTE = 'CLIENTE', 'Cliente'
        AUTOMATICO = 'AUTOMATICO', 'Atendimento automático'
        HUMANO = 'HUMANO', 'Equipe'
        SISTEMA = 'SISTEMA', 'Sistema'

    class Tipo(models.TextChoices):
        TEXTO = 'TEXTO', 'Texto'
        AUDIO = 'AUDIO', 'Áudio'
        IMAGEM = 'IMAGEM', 'Imagem'
        VIDEO = 'VIDEO', 'Vídeo'
        DOCUMENTO = 'DOCUMENTO', 'Documento'
        FIGURINHA = 'FIGURINHA', 'Figurinha'
        LOCALIZACAO = 'LOCALIZACAO', 'Localização'
        CONTATO = 'CONTATO', 'Contato'
        REACAO = 'REACAO', 'Reação'
        DESCONHECIDO = 'DESCONHECIDO', 'Não suportada'

    class Origem(models.TextChoices):
        NENHUMA = '', 'Conversa'
        ABERTURA = 'ABERTURA', 'Mensagem de abertura'
        BOAS_VINDAS = 'BOAS_VINDAS', 'Boas-vindas'
        PROGRAMADA = 'PROGRAMADA', 'Programada'

    class Status(models.TextChoices):
        RECEBIDO = 'RECEBIDO', 'Recebido'
        PENDENTE = 'PENDENTE', 'Enviando'
        ENVIADO = 'ENVIADO', 'Enviado'
        ENTREGUE = 'ENTREGUE', 'Entregue'
        LIDO = 'LIDO', 'Lido'
        ERRO = 'ERRO', 'Erro'

    class Transcricao(models.TextChoices):
        NENHUMA = '', '—'
        PENDENTE = 'PENDENTE', 'Pendente'
        OK = 'OK', 'Transcrito'
        ERRO = 'ERRO', 'Erro'

    conversa = models.ForeignKey(Conversa, on_delete=models.PROTECT, related_name='mensagens')
    direcao = models.CharField(max_length=7, choices=Direcao.choices)
    autor = models.CharField(max_length=10, choices=Autor.choices)
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.TEXTO)
    texto = models.TextField(blank=True, default='')
    responde_a = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='respostas',
    )
    dados = models.JSONField(default=dict, blank=True)
    origem = models.CharField(max_length=12, choices=Origem.choices, blank=True, default='')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    # NULL em vez de "" para o índice único funcionar também no MySQL (sem índice parcial).
    wa_message_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    midia_id = models.CharField(max_length=128, blank=True, default='')
    transcricao_status = models.CharField(max_length=8, choices=Transcricao.choices, blank=True, default='')
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.RECEBIDO)
    erro = models.TextField(blank=True, default='')
    lida_em = models.DateTimeField(null=True, blank=True)
    envio_iniciado_em = models.DateTimeField(null=True, blank=True)
    processada = models.BooleanField(default=False)
    criado_em = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['criado_em', 'id']
        default_permissions = ()
        indexes = [
            models.Index(fields=['conversa', 'criado_em']),
            models.Index(fields=['conversa', 'id']),
            models.Index(fields=['processada', 'direcao']),
        ]

    def __str__(self) -> str:
        return f'{self.get_direcao_display()} {self.get_tipo_display()} #{self.pk}'


class Midia(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        OK = 'OK', 'OK'
        ERRO = 'ERRO', 'Erro'
        EXPIRADA = 'EXPIRADA', 'Expirada'

    mensagem = models.OneToOneField(Mensagem, on_delete=models.CASCADE, related_name='midia')
    arquivo = models.FileField(upload_to=caminho_arquivo, max_length=300, blank=True)
    miniatura = models.FileField(upload_to=caminho_miniatura, max_length=300, blank=True)
    arquivo_envio = models.FileField(upload_to=caminho_envio, max_length=300, blank=True)
    mime = models.CharField(max_length=120, blank=True, default='')
    nome_original = models.CharField(max_length=255, blank=True, default='')
    tamanho_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    duracao_s = models.PositiveIntegerField(null=True, blank=True)
    largura = models.PositiveIntegerField(null=True, blank=True)
    altura = models.PositiveIntegerField(null=True, blank=True)
    voz = models.BooleanField(default=False)
    wa_media_id = models.CharField(max_length=128, blank=True, default='')
    sha256 = models.CharField(max_length=100, blank=True, default='')
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDENTE)
    tentativas = models.PositiveSmallIntegerField(default=0)
    erro = models.TextField(blank=True, default='')
    baixado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()


class LogAcessoMidia(models.Model):
    """Trilha LGPD: cada URL assinada de mídia entregue a um usuário."""

    midia = models.ForeignKey(Midia, on_delete=models.CASCADE, related_name='acessos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default='')
    acessado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()


class Nota(models.Model):
    class Tipo(models.TextChoices):
        GERAL = 'GERAL', 'Geral'
        TRANSFERENCIA = 'TRANSFERENCIA', 'Transferência'

    conversa = models.ForeignKey(Conversa, on_delete=models.PROTECT, related_name='notas')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    texto = models.TextField(max_length=2000)
    automatica = models.BooleanField(default=False)
    tipo = models.CharField(max_length=14, choices=Tipo.choices, default=Tipo.GERAL)
    silenciosa = models.BooleanField(default=False)
    criado_em = models.DateTimeField(default=timezone.now)
    apagada_em = models.DateTimeField(null=True, blank=True)
    apagada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['criado_em', 'id']
        default_permissions = ()


class MensagemProgramada(models.Model):
    class Status(models.TextChoices):
        AGENDADA = 'AGENDADA', 'Agendada'
        ENVIANDO = 'ENVIANDO', 'Enviando'
        ENVIADA = 'ENVIADA', 'Enviada'
        CANCELADA = 'CANCELADA', 'Cancelada'
        ERRO = 'ERRO', 'Erro'

    conversa = models.ForeignKey(Conversa, on_delete=models.PROTECT, related_name='programadas')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    texto = models.TextField(max_length=LIMITE_TEXTO)
    enviar_em = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.AGENDADA, db_index=True)
    mensagem = models.ForeignKey(Mensagem, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    erro = models.TextField(blank=True, default='')
    cancelada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['enviar_em', 'id']
        default_permissions = ()


class ConfiguracaoCRM(models.Model):
    """Configuração única do atendimento (pk = 1). Segredos ficam no ambiente, nunca aqui."""

    boas_vindas_ativa = models.BooleanField(default=True)
    mensagem_boas_vindas = models.TextField(
        max_length=1000,
        default='Olá! Recebemos sua mensagem e em instantes alguém da nossa equipe vai te atender.',
    )
    retorno_automatico_horas = models.PositiveSmallIntegerField(default=24)
    nome_empresa = models.CharField(max_length=80, default='IPX')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()

    @classmethod
    def obter(cls) -> 'ConfiguracaoCRM':
        config, _ = cls.objects.get_or_create(pk=1)
        return config
