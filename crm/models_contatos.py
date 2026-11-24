"""Contatos da cobrança: telefones de cada cliente, tentativas de contato e encaminhamentos da IA.

Regras (proposta de cobrança, 2026-11):
- O telefone principal do cadastro nunca é trocado automaticamente; os outros números
  entram aqui com a origem (atendimento, C4M, referência).
- Número de referência nunca recebe aviso de cobrança nem dado financeiro do cliente.
- Falta de resposta não é bloqueio: bloqueio só quando a equipe confirma.
"""
from django.conf import settings
from django.db import models


class TelefoneCliente(models.Model):
    class Origem(models.TextChoices):
        CADASTRO = 'CADASTRO', 'Cadastro'
        ATENDIMENTO = 'ATENDIMENTO', 'Usado pelo cliente no atendimento'
        C4M = 'C4M', 'Localizado no C4M'
        REFERENCIA = 'REFERENCIA', 'Referência'
        OUTRO = 'OUTRO', 'Outro'

    class Situacao(models.TextChoices):
        NAO_VERIFICADO = 'NAO_VERIFICADO', 'Não verificado'
        VALIDO = 'VALIDO', 'Confirmado do cliente'
        SEM_WHATSAPP = 'SEM_WHATSAPP', 'Sem WhatsApp'
        INVALIDO = 'INVALIDO', 'Número inválido'
        BLOQUEADO = 'BLOQUEADO', 'Bloqueio confirmado'

    cliente = models.ForeignKey('vendas.Cliente', on_delete=models.CASCADE, related_name='telefones_crm')
    telefone = models.CharField(max_length=20)
    origem = models.CharField(max_length=12, choices=Origem.choices)
    situacao = models.CharField(max_length=14, choices=Situacao.choices, default=Situacao.NAO_VERIFICADO)
    nome_contato = models.CharField(max_length=100, blank=True, default='',
                                    help_text='Nome da referência ou de quem atende neste número.')
    observacao = models.CharField(max_length=255, blank=True, default='')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['cliente', 'criado_em', 'id']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['cliente', 'telefone'], name='crm_telefone_unico_por_cliente'),
        ]

    def __str__(self) -> str:
        return f'{self.telefone} ({self.get_origem_display()})'


class TentativaContato(models.Model):
    """Histórico único: avisos automáticos (com parcela) e tentativas registradas pela equipe."""

    class Tipo(models.TextChoices):
        AVISO_ANTES = 'AVISO_ANTES', 'Lembrete antes do vencimento'
        AVISO_DIA = 'AVISO_DIA', 'Aviso no dia do vencimento'
        AVISO_APOS = 'AVISO_APOS', 'Pedido de comprovante após o vencimento'
        AVISO_INSISTENCIA = 'AVISO_INSIST', 'Nova tentativa sem retorno'
        AVISO_QUITACAO = 'AVISO_QUITAC', 'Mensagem de quitação'
        MANUAL = 'MANUAL', 'Registrada pela equipe'

    class Canal(models.TextChoices):
        WHATSAPP = 'WHATSAPP', 'WhatsApp'
        LIGACAO = 'LIGACAO', 'Ligação'

    class Resultado(models.TextChoices):
        ENVIADO = 'ENVIADO', 'Enviado, sem resposta'
        RESPONDEU = 'RESPONDEU', 'Cliente respondeu'
        FALHOU = 'FALHOU', 'Não entregue'
        NAO_ATENDEU = 'NAO_ATENDEU', 'Não atendeu'
        SEM_WHATSAPP = 'SEM_WHATSAPP', 'Sem WhatsApp'
        NUMERO_INVALIDO = 'INVALIDO', 'Número inválido'
        BLOQUEIO_CONFIRMADO = 'BLOQUEADO', 'Bloqueio confirmado'
        REFERENCIA_SEM_SUCESSO = 'REF_SEM_SUC', 'Referência não ajudou'
        REFERENCIA_AJUDOU = 'REF_AJUDOU', 'Referência ajudou'

    cliente = models.ForeignKey('vendas.Cliente', on_delete=models.CASCADE, related_name='tentativas_crm')
    telefone = models.ForeignKey(TelefoneCliente, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='tentativas')
    numero = models.CharField(max_length=20, help_text='Número usado (fica mesmo se o telefone for removido).')
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.MANUAL)
    canal = models.CharField(max_length=8, choices=Canal.choices, default=Canal.WHATSAPP)
    resultado = models.CharField(max_length=12, choices=Resultado.choices, default=Resultado.ENVIADO,
                                 db_index=True)
    parcela = models.ForeignKey('vendas.Parcela', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='avisos_crm')
    sequencia = models.PositiveSmallIntegerField(default=0)
    mensagem = models.ForeignKey('crm.Mensagem', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='tentativas')
    observacao = models.CharField(max_length=255, blank=True, default='')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    respondido_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-criado_em', '-id']
        default_permissions = ()
        constraints = [
            # Um aviso de cada etapa por parcela (NULL em parcela não conflita: tentativas manuais).
            models.UniqueConstraint(fields=['parcela', 'tipo', 'sequencia'], name='crm_aviso_unico_por_etapa'),
        ]
        indexes = [models.Index(fields=['cliente', 'criado_em'])]

    @property
    def automatica(self) -> bool:
        return self.tipo != self.Tipo.MANUAL


class EncaminhamentoIA(models.Model):
    """Cada transferência feita pelo assistente, com o assunto (indicadores do painel)."""

    class Assunto(models.TextChoices):
        DESBLOQUEIO = 'DESBLOQUEIO', 'Desbloqueio do aparelho'
        COMPROVANTE = 'COMPROVANTE', 'Comprovante de pagamento'
        NEGOCIACAO = 'NEGOCIACAO', 'Negociação de dívida'
        QUITACAO = 'QUITACAO', 'Oferta de quitação'
        ANTECIPACAO = 'ANTECIPACAO', 'Antecipação de parcela'
        NOVO_APARELHO = 'NOVO_APARELHO', 'Quitou e quer outro aparelho'
        CONSULTA = 'CONSULTA', 'IPX Consulta'
        VENCIMENTO = 'VENCIMENTO', 'Mudança de vencimento'
        ATENDENTE = 'ATENDENTE', 'Pediu atendente'
        RECLAMACAO = 'RECLAMACAO', 'Reclamação'
        OUTRO = 'OUTRO', 'Outro assunto'

    conversa = models.ForeignKey('crm.Conversa', on_delete=models.PROTECT, related_name='encaminhamentos')
    assunto = models.CharField(max_length=14, choices=Assunto.choices, default=Assunto.OUTRO, db_index=True)
    fora_do_horario = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-criado_em', '-id']
        default_permissions = ()
