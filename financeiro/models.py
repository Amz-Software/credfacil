from datetime import datetime
from django.db import models
from django.urls import reverse
from vendas.models import Base


class CaixaMensal(Base):
    loja = models.ForeignKey('vendas.Loja', on_delete=models.PROTECT, related_name='caixas_mensais')
    mes = models.DateField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data_abertura = models.DateTimeField(auto_now_add=True)
    data_fechamento = models.DateTimeField(blank=True, null=True)
    gasto_fixos = models.ManyToManyField('financeiro.GastoFixo', through='financeiro.CaixaMensalGastoFixo', related_name='gastos_fixos')
    funcionarios = models.ManyToManyField('self', through='financeiro.CaixaMensalFuncionario')
    
    def calcular_saldo(self):
        total_gastos_fixos = sum(gasto.valor for gasto in self.gastos_fixos.all())
        total_funcionarios = sum(funcionario.salario + funcionario.comissao for funcionario in self.funcionarios.all())
        total_gastos_aleatorios = sum(gasto.valor for gasto in self.gastos_aleatorios.all())
        total_despesas = total_gastos_fixos + total_funcionarios + total_gastos_aleatorios
        self.valor -= total_despesas
        self.save()
        
    
    def fechar(self):
        self.data_fechamento = datetime.now()
        self.save()
        
    def reabrir(self):
        self.data_fechamento = None
        self.save()
        
    def __str__(self):
        return f'{self.loja} - {self.mes}'
    
    def get_absolute_url(self):
        return reverse('financeiro:caixa_mensal_update', args=[self.pk])
    
    class Meta:
        verbose_name_plural = 'Caixas Mensais'
        verbose_name = 'Caixa Mensal'
        constraints = [
            models.UniqueConstraint(fields=['loja', 'mes'], name='unique_caixa_mensal_por_loja_mes')
        ]
        

class GastoFixo(Base):
    nome = models.CharField(max_length=100)
    
    def __str__(self):
        return self.nome
    
    class Meta:
        verbose_name_plural = 'Gastos Fixos'
        


class CaixaMensalGastoFixo(Base):
    caixa_mensal = models.ForeignKey('financeiro.CaixaMensal', on_delete=models.CASCADE, related_name='gastos_fixos_caixa_mensal')
    gasto_fixo = models.ForeignKey('financeiro.GastoFixo', on_delete=models.CASCADE)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    observacao = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f'{self.caixa_mensal} - {self.gasto_fixo}'
    
    class Meta:
        verbose_name_plural = 'Gastos Fixos por Loja'
        verbose_name = 'Gasto Fixo por Loja'
        constraints = [
            models.UniqueConstraint(fields=['caixa_mensal', 'gasto_fixo'], name='unique_gasto_fixo_por_caixa_mensal')
        ]

class CaixaMensalFuncionario(Base):
    caixa_mensal = models.ForeignKey('financeiro.CaixaMensal', on_delete=models.CASCADE)
    funcionario = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    comissao = models.DecimalField(max_digits=10, decimal_places=2)
    salario = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f'{self.caixa_mensal} - {self.funcionario}'
    
    
    class Meta:
        verbose_name_plural = 'Funcionários por Loja'
        verbose_name = 'Funcionário por Loja'
        

class GastosAleatorios(Base):
    caixa_mensal = models.ForeignKey('financeiro.CaixaMensal', on_delete=models.CASCADE, related_name='gastos_aleatorios')
    descricao = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    observacao = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f'{self.caixa_mensal.loja} - {self.descricao}'

    
    class Meta:
        verbose_name_plural = 'Gastos Aleatórios'
        verbose_name = 'Gasto Aleatório'



class Repasse(models.Model):
    loja = models.ForeignKey('vendas.Loja', on_delete=models.PROTECT, related_name='repasse')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[('pendente', 'Pendente'), ('pago', 'Pago'), ('cancelado', 'Cancelado')], default='pendente')
    # Perguntar
    # dias_repasse = models.CharField(max_length=10, choices=[('1', '1 dia'), ('10', '10 dias'), ('20', '20 dias')])
    observacao = models.TextField(blank=True, null=True)
    criado_por = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='repasse_criado_por')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_por = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='repasse_atualizado_por')
    atualizado_em = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f'{self.loja} - {self.valor}'
    
    class Meta:
        verbose_name_plural = 'Repasse'
        verbose_name = 'Repasse'
        ordering = ['-data']
        permissions = (
            ('add_notificacaobo', 'Pode gerar notificação BO'),
        )