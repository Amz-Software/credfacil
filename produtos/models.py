from django.db import models
from vendas.models import Base

class Marca(Base):
    ICONE_CHOICES = (
        ('bi bi-apple', 'Apple'),
        ('bx bx-mobile', 'Celular (Padrão/Samsung)'),
        ('bx bx-mobile-alt', 'Celular 2 (Xiaomi/Outros)'),
        ('bi bi-phone', 'Celular 3 (Motorola)'),
        ('bx bx-laptop', 'Notebook / Tablet'),
        ('bx bx-devices', 'Múltiplos Dispositivos'),
    )
    
    nome = models.CharField(max_length=100)
    cor = models.CharField(max_length=20, default='#007bff', help_text='Código HEX ou nome da cor (Ex: #ff0000, primary, etc)')
    icone = models.CharField(max_length=50, choices=ICONE_CHOICES, default='bx bx-mobile', help_text='Selecione o ícone da marca que aparecerá no sistema')
    ativo = models.BooleanField(default=True, verbose_name='Ativo', help_text='Desmarcar irá esconder a marca no painel de solicitação.')
    lojas_permitidas = models.ManyToManyField(
        'vendas.Loja',
        blank=True,
        related_name='marcas_permitidas',
        verbose_name='Lojas Permitidas',
        help_text='Selecione as lojas que podem ver esta marca. Se nenhuma for selecionada, a marca ficará visível para todas as lojas.'
    )

    def __str__(self):
        return self.nome

    class Meta:
        ordering = ['nome']
        verbose_name = 'Marca'
        verbose_name_plural = 'Marcas'


class Produto(Base):
    codigo = models.IntegerField(unique=True, blank=True, null=True)
    nome = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name='Valor Base')
    entrada_cliente = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='Entrada Mínima')
    tipo = models.ForeignKey('produtos.TipoProduto', on_delete=models.PROTECT, related_name='produtos_tipo', null=True, blank=True)
    marca = models.ForeignKey('produtos.Marca', on_delete=models.PROTECT, related_name='produtos_marca', null=True, blank=True)
    ativo = models.BooleanField(default=True)
    is_iphone = models.BooleanField(default=False, verbose_name='É iPhone?')
    
    def gerar_codigo(self):
        last_product = Produto.objects.all().order_by('codigo').last()
        if not last_product:
            self.codigo = 1
        else:
            self.codigo = last_product.codigo + 1

    def save(self, *args, **kwargs):
        if not self.pk:
            if not self.codigo:
                self.gerar_codigo()
        else:
            if not self.codigo:
                self.codigo = Produto.objects.filter(pk=self.pk).values_list('codigo', flat=True).first()
        super(Produto, self).save(*args, **kwargs)
        
    def delete(self, *args, **kwargs):
        # Soft delete: apenas marca como inativo, não remove do banco
        self.ativo = False
        self.save()
    
    def total_vendas(self, loja_id=None):
        if loja_id:
            return self.produto_vendas.filter(venda__loja_id=loja_id, venda__is_deleted=False).count()
        return None
    
    def __str__(self):
        return f"{self.nome} ({self.codigo})"
    
    class Meta:
        ordering = ['codigo']
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        permissions = (
            ('view_all_produtos', 'Can view all produtos'),
        )


class Parcelamento(Base):
    marca = models.ForeignKey('produtos.Marca', on_delete=models.CASCADE, related_name='parcelamentos', null=True, blank=True)
    qtd_vezes = models.IntegerField(verbose_name='Quantidade de vezes')
    porcentagem_juros = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Porcentagem de juros (%)')
    porcentagem_desconto = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name='Porcentagem de desconto (%)')

    def __str__(self):
        marca_nome = self.marca.nome if self.marca else '—'
        return f"{marca_nome} — {self.qtd_vezes}x — {self.porcentagem_juros}%"

    class Meta:
        ordering = ['marca', 'qtd_vezes']
        verbose_name = 'Parcelamento'
        verbose_name_plural = 'Parcelamentos'
        unique_together = [('marca', 'qtd_vezes')]


class TipoProduto(Base):
    nome = models.CharField(max_length=100)
    numero_serial = models.BooleanField(default=False)
    assistencia = models.BooleanField(default=False)

    def __str__(self):
        return self.nome

class CorProduto(Base):
    nome = models.CharField(max_length=100)

    def __str__(self):
        return self.nome

class Fabricante(Base):
    nome = models.CharField(max_length=100)

    def __str__(self):
        return self.nome

class MemoriaProduto(Base):
    nome = models.CharField(max_length=100)

    def __str__(self):
        return self.nome

class EstadoProduto(Base):
    nome = models.CharField(max_length=100)

    def __str__(self):
        return self.nome
