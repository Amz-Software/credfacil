from django.db import models
from vendas.models import Base
from django.urls import reverse
import datetime


class EntradaEstoque(Base):
    fornecedor = models.ForeignKey('estoque.Fornecedor', on_delete=models.PROTECT, related_name='entradas_estoque', verbose_name='Fornecedor', blank=True, null=True)
    data_entrada = models.DateTimeField(verbose_name='Data de Entrada', auto_now_add=True)
    numero_nota = models.CharField(max_length=20, verbose_name='Número da Nota', blank=True)
    venda_liberada = models.BooleanField(default=False, verbose_name='Liberada para Venda')
    
    def save(self, *args, **kwargs):
        if not self.numero_nota:
            # Gerar número automático baseado no ano atual e sequencial
            ano_atual = self.data_entrada.year if self.data_entrada else datetime.datetime.now().year
            ultima_entrada = EntradaEstoque.objects.filter(
                numero_nota__startswith=f'ENT{ano_atual}'
            ).order_by('-numero_nota').first()
            
            if ultima_entrada and ultima_entrada.numero_nota:
                try:
                    # Extrair o número sequencial da última entrada
                    ultimo_numero = int(ultima_entrada.numero_nota.split('-')[-1])
                    novo_numero = ultimo_numero + 1
                except (ValueError, IndexError):
                    novo_numero = 1
            else:
                novo_numero = 1
            
            # Formato: ENT2024-0001, ENT2024-0002, etc.
            self.numero_nota = f'ENT{ano_atual}-{novo_numero:04d}'
        
        super().save(*args, **kwargs)
    
    @property
    def custo_total(self):
        total = 0
        for produto in self.produtos.all():
            total += produto.custo_total
        return total

    @property
    def venda_total(self):
        total = 0
        for produto in self.produtos.all():
            total += produto.venda_total
        return total
    
    @property
    def quantidade_total(self):
        total = 0
        for produto in self.produtos.all():
            total += produto.quantidade
        return total
    
    def count_produtos(self):
        return self.produtos.count()
    
    def __str__(self):
        return f"Entrada {self.numero_nota}"

    class Meta:
        verbose_name = 'Entrada de Estoque'
        verbose_name_plural = 'Entradas de Estoque'
        ordering = ['-data_entrada']
        permissions = (
            ('can_liberar_venda', 'Pode liberar venda'),
        )

class ProdutoEntrada(Base):
    entrada = models.ForeignKey(EntradaEstoque, on_delete=models.CASCADE, related_name='produtos', verbose_name='Entrada de Estoque')
    produto = models.ForeignKey('produtos.Produto', on_delete=models.PROTECT, related_name='entradas_estoque', verbose_name='Produto')
    imei = models.CharField(max_length=20, blank=True, null=True, verbose_name='IMEI')
    custo_unitario = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Custo Unitário', blank=True, null=True)
    venda_unitaria = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Venda Unitária', blank=True, null=True)
    quantidade = models.PositiveIntegerField(verbose_name='Quantidade', default=1)

    @property
    def custo_total(self):
        if self.custo_unitario is None:
            return 0
        return self.custo_unitario * self.quantidade
    
    @property
    def venda_total(self):
        if self.venda_unitaria is None:
            return 0
        return self.venda_unitaria * self.quantidade

    def __str__(self):
        return f"{self.produto.nome} - Quantidade: {self.quantidade}"

    class Meta:
        verbose_name = 'Produto na Entrada de Estoque'
        verbose_name_plural = 'Produtos na Entrada de Estoque'
        ordering = ['entrada__data_entrada']
        

class EstoqueImei(Base):
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE, related_name='estoque_imei')
    imei = models.CharField(max_length=20, verbose_name='IMEI')
    vendido = models.BooleanField(default=False, verbose_name='Vendido')
    data_venda = models.DateTimeField(blank=True, null=True, verbose_name='Data da Venda')
    produto_entrada = models.ForeignKey(ProdutoEntrada, on_delete=models.CASCADE, related_name='estoque_imei', blank=True, null=True)
    aplicativo_instalado = models.BooleanField(default=False, verbose_name='Aplicativo Instalado')
    cancelado = models.BooleanField(default=False, verbose_name='Cancelado')
    
    @property
    def id_venda(self):
        """Retorna o ID da venda relacionada ao IMEI"""
        if self.vendido:
            # Busca a venda através do ProdutoVenda que contém este IMEI
            from vendas.models import ProdutoVenda
            produto_venda = ProdutoVenda.objects.filter(imei=self.imei).first()
            return produto_venda.venda.id if produto_venda else None
        return None
    
    @property
    def numero_nota(self):
        """Retorna o número da nota da entrada relacionada ao IMEI"""
        if self.produto_entrada and self.produto_entrada.entrada:
            return self.produto_entrada.entrada.numero_nota
        return None
    
    def __str__(self):
        return self.imei
    
    class Meta:
        unique_together = ['imei', 'produto', 'loja']
        verbose_name = 'Estoque IMEI'
        verbose_name_plural = 'Estoques IMEI'
        permissions = (
            ('can_view_all_imei', 'Pode visualizar todos os IMEI'),
        )


class Estoque(Base):
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE, related_name='estoque_atual')
    quantidade_disponivel = models.PositiveIntegerField(default=0)

    def quantidade(self):
        # busca todas unidades do produto no estoque dessa loja
        return self.produto.estoque_imei.filter(produto__nome=self.produto.nome, loja=self.loja, vendido=False, cancelado=False).count()
    
    def quantidade_vendida(self):
        # busca todas unidades do produto no estoque que foram vendidas
        return self.produto.estoque_imei.filter(produto__nome=self.produto.nome, loja=self.loja, vendido=True, cancelado=False).count()

    @property
    def ultima_entrada(self):
        return self.produto.entradas_estoque.last()
    
    def preco_medio(self):
        qtd_entradas = self.produto.entradas_estoque.count()
        total = 0
        for entrada in self.produto.entradas_estoque.all():
            if entrada.venda_unitaria is not None:
                total += entrada.venda_unitaria or 0
            else:
                total += 0

        if qtd_entradas > 0:
            preco_medio = total / qtd_entradas
            preco_formatado = f"{preco_medio:.2f}"
            return preco_formatado
        return 0
    
    def preco_medio_custo(self):
        qtd_entradas = self.produto.entradas_estoque.count()
        total = 0
        for entrada in self.produto.entradas_estoque.all():
            if entrada.custo_unitario is not None:
                total += entrada.custo_unitario or 0
            else:
                total += 0
        
        if qtd_entradas > 0:
            preco_medio = total / qtd_entradas
            preco_formatado = f"{preco_medio:.2f}"
            return preco_formatado
        return 0
    
    def adicionar_estoque(self, quantidade):
        self.quantidade_disponivel += quantidade
        self.save()
        
    def remover_estoque(self, quantidade):
        if self.quantidade_disponivel >= quantidade:
            self.quantidade_disponivel -= quantidade
            self.save()
        else:
            raise ValueError("Estoque insuficiente.")
 
    def __str__(self):
        return f"Estoque de {self.produto.nome}: {self.quantidade_disponivel}"
    
    class Meta:
        unique_together = ['loja', 'produto']
        verbose_name_plural = 'Estoques'
        ordering = ['quantidade_disponivel']


class Fornecedor(Base):
    nome = models.CharField(max_length=100)
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    
    def __str__(self):
        return self.nome
    
    class Meta:
        verbose_name_plural = 'Fornecedores'