"""Pagamento online de parcelas pelo PagBank: configuração e cobranças geradas.

O token do PagBank fica no ambiente (`PAGBANK_TOKEN`), nunca no banco.
"""
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models

ZERO = Decimal('0.00')


class ConfiguracaoPagamentoOnline(models.Model):
    """Configuração única (pk = 1), editada no backoffice."""

    ativo = models.BooleanField(
        default=False, help_text='Liga a geração de cobranças no PagBank (exige PAGBANK_TOKEN no servidor).',
    )
    pix_ativo = models.BooleanField(default=True)
    boleto_ativo = models.BooleanField(default=False)
    cartao_ativo = models.BooleanField(default=False)
    taxa_boleto = models.DecimalField(
        max_digits=8, decimal_places=2, default=ZERO,
        help_text='Tarifa fixa do boleto, somada ao valor da parcela (paga pelo cliente).',
    )
    taxa_cartao_percentual = models.DecimalField(
        max_digits=5, decimal_places=2, default=ZERO,
        help_text='Taxa do cartão (%). O total é calculado para a empresa receber o valor cheio.',
    )
    cartao_max_parcelas = models.PositiveSmallIntegerField(
        default=12, help_text='Parcelas no cartão; os juros do parcelamento ficam com o cliente.',
    )
    validade_horas = models.PositiveSmallIntegerField(
        default=24, help_text='Validade do Pix e do link do cartão depois de gerados.',
    )
    boleto_dias_vencimento = models.PositiveSmallIntegerField(default=3)
    email_padrao = models.EmailField(
        blank=True, default='', help_text='Usado na cobrança quando o cliente não tem e-mail cadastrado.',
    )
    uf_padrao = models.CharField(
        max_length=2, default='PA', help_text='UF do endereço no boleto (o cadastro do cliente não tem UF).',
    )
    url_app_cliente = models.CharField(
        max_length=200, blank=True, default='',
        help_text='Endereço do app do cliente (ex.: https://vendas.ipix.mobconnects.com).',
    )
    redirecionar_paginas_antigas = models.BooleanField(
        default=False, help_text='Leva as páginas públicas antigas do Django para o app do cliente.',
    )
    modificado_em = models.DateTimeField(auto_now=True)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = 'Configuração de pagamento online'
        verbose_name_plural = 'Configuração de pagamento online'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def obter(cls) -> 'ConfiguracaoPagamentoOnline':
        configuracao, _ = cls.objects.get_or_create(pk=1)
        return configuracao

    def link_app(self, caminho: str) -> str:
        base = self.url_app_cliente.strip().rstrip('/')
        return f'{base}/{caminho.lstrip("/")}' if base else ''


class Cobranca(models.Model):
    """Uma cobrança criada no PagBank: uma parcela, várias parcelas ou a quitação com desconto.

    `parcela` é a primeira parcela cobrada; todas ficam em `itens` (com o valor e o desconto de cada uma).
    """

    class Tipo(models.TextChoices):
        PARCELA = 'parcela', 'Parcela'
        PARCELAS = 'parcelas', 'Várias parcelas'
        QUITACAO = 'quitacao', 'Quitação'

    class Forma(models.TextChoices):
        PIX = 'pix', 'Pix'
        BOLETO = 'boleto', 'Boleto'
        CARTAO = 'cartao', 'Cartão de crédito'

    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Aguardando pagamento'
        PAGA = 'paga', 'Paga'
        EXPIRADA = 'expirada', 'Expirada'
        CANCELADA = 'cancelada', 'Cancelada'

    class Origem(models.TextChoices):
        CLIENTE = 'cliente', 'App do cliente'
        BOT = 'bot', 'Assistente do WhatsApp'
        BACKOFFICE = 'backoffice', 'Backoffice'

    referencia = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.PARCELA)
    parcela = models.ForeignKey('vendas.Parcela', on_delete=models.PROTECT, related_name='cobrancas_online')
    forma = models.CharField(max_length=10, choices=Forma.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDENTE, db_index=True)
    origem = models.CharField(max_length=12, choices=Origem.choices)
    valor_parcela = models.DecimalField(
        max_digits=10, decimal_places=2, help_text='Soma do que entra nas parcelas (já com o desconto da quitação).',
    )
    taxa = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    pagbank_id = models.CharField(max_length=64, blank=True, default='', db_index=True,
                                  help_text='ORDE_... (Pix/boleto) ou CHEC_... (cartão).')
    pagbank_pedido_id = models.CharField(max_length=64, blank=True, default='', db_index=True,
                                         help_text='Pedido (ORDE_...) que pagou o checkout de cartão.')
    pix_copia_cola = models.TextField(blank=True, default='')
    qr_code_url = models.URLField(max_length=500, blank=True, default='')
    boleto_linha_digitavel = models.CharField(max_length=80, blank=True, default='')
    boleto_pdf_url = models.URLField(max_length=500, blank=True, default='')
    link_pagamento = models.URLField(max_length=500, blank=True, default='')
    expira_em = models.DateTimeField()
    paga_em = models.DateTimeField(null=True, blank=True)
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    pagamento_duplicado = models.BooleanField(
        default=False, help_text='Paga quando a parcela já estava quitada: precisa de estorno ou acerto manual.',
    )
    acerto_manual = models.TextField(
        blank=True, default='', help_text='Divergência para a equipe resolver (valor a menor, excedente, pagamento extra).',
    )
    detalhes_pagamento = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    class Meta:
        verbose_name = 'Cobrança online'
        verbose_name_plural = 'Cobranças online'
        ordering = ['-criado_em', '-id']
        indexes = [models.Index(fields=['status', 'expira_em'])]

    def __str__(self) -> str:
        return f'{self.get_forma_display()} de R$ {self.valor_total} ({self.get_status_display()})'

    def itens_da_baixa(self) -> list['ItemCobranca']:
        """Itens em ordem de parcela; cobrança sem itens (anterior a eles) vira um item da própria parcela."""
        if 'itens' in getattr(self, '_prefetched_objects_cache', {}):
            itens = sorted(self.itens.all(), key=lambda i: (i.parcela.numero_parcela, i.parcela_id))
        else:
            itens = list(self.itens.select_related('parcela').order_by('parcela__numero_parcela', 'parcela_id'))
        return itens or [ItemCobranca(cobranca=self, parcela=self.parcela, valor=self.valor_parcela, desconto=ZERO)]

    def numeros_das_parcelas(self) -> list[int]:
        return [item.parcela.numero_parcela for item in self.itens_da_baixa()]


class ItemCobranca(models.Model):
    """Parcela paga por uma cobrança: `valor` é o que entra nela e `desconto` o abatido na quitação."""

    cobranca = models.ForeignKey(Cobranca, on_delete=models.CASCADE, related_name='itens')
    parcela = models.ForeignKey('vendas.Parcela', on_delete=models.PROTECT, related_name='itens_cobranca_online')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)

    class Meta:
        verbose_name = 'Parcela da cobrança online'
        verbose_name_plural = 'Parcelas da cobrança online'
        constraints = [models.UniqueConstraint(fields=['cobranca', 'parcela'], name='item_cobranca_unico')]


class RegistroPagBank(models.Model):
    """Requisição e resposta trocadas com o PagBank (exigidas na homologação). Nunca guarda o token."""

    class Tipo(models.TextChoices):
        CHAMADA = 'chamada', 'Chamada à API'
        NOTIFICACAO = 'notificacao', 'Notificação recebida'

    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    ambiente = models.CharField(max_length=10)
    metodo = models.CharField(max_length=8, blank=True, default='')
    caminho = models.CharField(max_length=200)
    status_http = models.PositiveSmallIntegerField(null=True, blank=True)
    requisicao = models.JSONField(null=True, blank=True)
    resposta = models.JSONField(null=True, blank=True)
    cobranca = models.ForeignKey(Cobranca, on_delete=models.SET_NULL, null=True, blank=True, related_name='registros')
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Registro PagBank'
        verbose_name_plural = 'Registros PagBank'
        ordering = ['-criado_em', '-id']
