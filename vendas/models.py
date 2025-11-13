from django.db import models
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
from django.utils.functional import cached_property
from django.db.models import Count, Q, Case, When, Value, IntegerField, BooleanField, F, Min
from django.db import models
from django.utils import timezone
from django.urls import reverse
import re
from django.utils.text import slugify
import calendar

class Base(models.Model):
    loja = models.ForeignKey('vendas.Loja', on_delete=models.CASCADE, related_name='%(class)s_loja', null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True,editable=False)
    modificado_em = models.DateTimeField(auto_now=True,editable=False)
    criado_por = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='%(class)s_criadas',editable=False, null=True, blank=True)
    modificado_por = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='%(class)s_modificadas',editable=False, null=True, blank=True)
    
    def save(self, *args, user=None, **kwargs):
        if user:
            if not self.pk: 
                self.criado_por = user
            self.modificado_por = user
        super().save(*args, **kwargs)
        
    class Meta:
        abstract = True


class Caixa(Base):
    data_abertura = models.DateField(default=timezone.now)
    data_fechamento = models.DateField(null=True, blank=True)
    
    @property
    def saldo_total(self):
        return sum(venda.pagamentos_valor_total for venda in self.vendas.filter(is_deleted=False).filter(loja=self.loja).filter(caixa=self))
    
    def saldo_caixa(self):
        return sum(venda.valor_caixa for venda in self.vendas.filter(is_deleted=False).filter(loja=self.loja).filter(caixa=self))
    
    @property
    def saldo_total_dinheiro(self):
        total = sum(venda.pagamentos_valor_total_dinheiro for venda in self.vendas.filter(is_deleted=False, pagamentos__tipo_pagamento__caixa=True).filter(loja=self.loja).filter(caixa=self))
        return total if total else 0
    
    def saldo_final(self):
        return (self.saldo_total_dinheiro + self.entradas) - self.saidas

    @property
    def saidas(self):
        return sum(lancamento.valor for lancamento in self.lancamentos_caixa.filter(tipo_lancamento='2'))
    
    @property
    def entradas(self):
        return sum(lancamento.valor for lancamento in self.lancamentos_caixa.filter(tipo_lancamento='1'))
    
    @property
    def quantidade_vendas(self):
        return self.vendas.filter(is_deleted=False).filter(loja=self.loja).filter(caixa=self).count()
    
    @property
    def caixa_fechado(self):
        if self.data_fechamento:
            return True
        return False
        
    
    @classmethod
    def caixa_aberto(cls, data, loja):
        return cls.objects.filter(data_abertura=data, data_fechamento__isnull=True, loja=loja).exists()

    def __str__(self):
        return f"Caixa do dia {self.data_abertura} - {self.loja}"

    class Meta:
        verbose_name_plural = 'Caixas'
        ordering = ['-data_abertura']

class LancamentoCaixaTotal(Base):
    tipo_lancamento_opcoes = (
        ('1', 'Crédito'),
        ('2', 'Débito'),
    )

    motivo = models.CharField(max_length=100)
    tipo_lancamento = models.CharField(max_length=1, choices=tipo_lancamento_opcoes)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"{self.tipo_lancamento} - R$ {self.valor}"
    
    class Meta:
        verbose_name_plural = 'Lancamentos Caixa Total'

class LancamentoCaixa(Base):
    tipo_lancamento_opcoes = (
        ('1', 'Crédito'),
        ('2', 'Débito'),
    )

    caixa = models.ForeignKey('vendas.Caixa', on_delete=models.CASCADE, related_name='lancamentos_caixa')
    motivo = models.CharField(max_length=100)
    tipo_lancamento = models.CharField(max_length=1, choices=tipo_lancamento_opcoes)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"{self.tipo_lancamento} - R$ {self.valor}"
    
    class Meta:
        verbose_name_plural = 'Lancamentos Caixa'


from django.db.models import Count, Case, When, Value, IntegerField
from datetime import date

class LojaQuerySet(models.QuerySet):
    def com_repasse_pendente(self):
        hoje = date.today()
        return self.annotate(
            repasses_pendentes=Count(
                Case(
                    When(
                        repasse__status='pendente',  # Apenas repasses com status 'pendente'
                        repasse__data__lte=hoje,  # E com data do repasse até hoje
                        then=Value(1)
                    ),
                    default=Value(0),
                    output_field=IntegerField()
                )
            )
        ).filter(repasses_pendentes__gt=0)  # Apenas lojas com repasses pendentes

    def sem_repasse_pendente(self):
        hoje = date.today()
        return self.annotate(
            repasses_pendentes=Count(
                Case(
                    When(
                        repasse__status='pendente',  # Apenas repasses com status 'pendente'
                        repasse__data__lte=hoje,  # E com data do repasse até hoje
                        then=Value(1)
                    ),
                    default=Value(0),
                    output_field=IntegerField()
                )
            )
        ).filter(repasses_pendentes=0)  # Apenas lojas sem repasses pendentes


class Loja(Base):
    nome = models.CharField(max_length=100)
    cnpj = models.CharField(max_length=14, null=True, blank=True)
    inscricao_estadual = models.CharField(max_length=20, null=True, blank=True)
    endereco = models.CharField(max_length=200, null=True, blank=True)
    telefone = models.CharField(max_length=20, null=True, blank=True)
    meta_vendas_diaria = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    meta_vendas_mensal = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    entrada_caixa_diaria = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    logo_loja = models.ImageField(upload_to='logos_lojas/', null=True, blank=True)
    mensagem_garantia = models.TextField(null=True, blank=True)
    contrato = models.JSONField(null=True, blank=True, default=dict)
    usuarios = models.ManyToManyField('accounts.User', related_name='lojas')
    gerentes = models.ManyToManyField('accounts.User', related_name='lojas_gerenciadas')
    chave_pix = models.CharField(max_length=100, null=True, blank=True)
    credfacil = models.BooleanField(default=False)
    porcentagem_desconto_4 = models.DecimalField(max_digits=5, decimal_places=2, default=25.00)
    porcentagem_desconto_6 = models.DecimalField(max_digits=5, decimal_places=2, default=25.00)
    porcentagem_desconto_8 = models.DecimalField(max_digits=5, decimal_places=2, default=25.00)
    porcentagem_desconto_10 = models.DecimalField(max_digits=5, decimal_places=2, default=25.00)
    qr_code_aplicativo = models.ImageField(upload_to='qr_codes_aplicativo/', null=True, blank=True)
    codigo_aplicativo = models.CharField(max_length=100, null=True, blank=True)
    objects = LojaQuerySet.as_manager()


    REPASSES_DIAS = (1, 16)

    def get_repasses_status(self, meses_atras=0, limite_meses=6):
        hoje = date.today()
        resultados = []

        # Limita quantos meses olhar para trás
        meses_atras = min(meses_atras, limite_meses)

        # Queryset base de Vendas
        vendas_qs = self.venda_loja.all()

        for delta in range(meses_atras, -1, -1):
            ano = hoje.year
            mes = hoje.month - delta
            while mes <= 0:
                mes += 12
                ano -= 1

            for idx, dia in enumerate(self.REPASSES_DIAS):
                # Data do repasse (data de pagamento)
                try:
                    data_repasse = date(ano, mes, dia)
                except ValueError:
                    continue

                # Intervalos de competência por regra:
                # - Repasse do dia 01: período 16 até último dia do mês anterior
                # - Repasse do dia 16: período 01 até dia 15 do mês atual
                if dia == 1:
                    prev_mes, prev_ano = (mes - 1, ano)
                    if prev_mes == 0:
                        prev_mes, prev_ano = 12, ano - 1
                    ultimo_dia_prev_mes = calendar.monthrange(prev_ano, prev_mes)[1]
                    inicio = date(prev_ano, prev_mes, 16)
                    fim = date(prev_ano, prev_mes, ultimo_dia_prev_mes)
                else:  # dia == 16
                    inicio = date(ano, mes, 1)
                    fim = date(ano, mes, 15)

                vendas_periodo = vendas_qs.filter(
                    data_venda__date__gte=inicio,
                    data_venda__date__lte=fim,
                    is_deleted=False
                )

                qtd = vendas_periodo.count()
                if qtd == 0:
                    continue

                # Soma de valor_repasse_logista de cada venda
                valor = Decimal('0.00')
                for venda in vendas_periodo:
                    valor_repasse = venda.repasse_logista
                    valor += valor_repasse

                feito = self.repasse.filter(data__date=data_repasse).exists()

                # Verifica se o valor do repasse é menor que o calculado
                if feito:
                    repasses = self.repasse.filter(data__date=data_repasse)
                    for repasse in repasses:
                        if repasse.valor < valor:
                            # Se o valor do repasse for menor que o calculado, marca como parcial
                            repasse.status = 'parcial'
                            repasse.save()

                resultados.append({
                    'data': data_repasse,
                    'inicio_periodo': inicio,
                    'fim_periodo': fim,
                    'qtd_vendas': qtd,
                    'valor_total_repasse': valor,
                    'feito': feito,
                })

        atrasados = sum(1 for rep in resultados if not rep['feito'] and rep['data'] < hoje)
        return resultados, atrasados

        
    def calcular_valor_repasse(self, data_inicio, data_fim):
        if data_inicio and data_fim:
            vendas = self.venda_loja.filter(data_venda__date__gte=data_inicio, data_venda__date__lte=data_fim, is_deleted=False)
            valor_repasse = sum(
                venda.repasse_logista if venda.repasse_logista else sum(
                    produto.produto.valor_repasse_logista * produto.quantidade
                    for produto in ProdutoVenda.objects.filter(venda=venda)
                )
                for venda in vendas
            )
            return valor_repasse

        elif data_inicio:
            vendas = self.venda_loja.filter(data_venda__date__gte=data_inicio, is_deleted=False)
            valor_repasse = sum(
                venda.repasse_logista if venda.repasse_logista else sum(
                    produto.produto.valor_repasse_logista * produto.quantidade
                    for produto in ProdutoVenda.objects.filter(venda=venda)
                )
                for venda in vendas
            )
            return valor_repasse

        elif data_fim:
            vendas = self.venda_loja.filter(data_venda__date__lte=data_fim, is_deleted=False)
            valor_repasse = sum(
                venda.repasse_logista if venda.repasse_logista else sum(
                    produto.produto.valor_repasse_logista * produto.quantidade
                    for produto in ProdutoVenda.objects.filter(venda=venda)
                )
                for venda in vendas
            )
            return valor_repasse

        else:
            vendas = self.venda_loja.filter(is_deleted=False)
            valor_repasse = sum(
                venda.repasse_logista if venda.repasse_logista else sum(
                    produto.produto.valor_repasse_logista * produto.quantidade
                    for produto in ProdutoVenda.objects.filter(venda=venda)
                )
                for venda in vendas
            )
            return valor_repasse

    def __str__(self):
        return self.nome
    
    class Meta:
        verbose_name_plural = 'Lojas'
        permissions = (
            ('can_view_all_stores', 'Pode ver todas as lojas'),
        )


class Cliente(Base):
    nome = models.CharField(max_length=100)
    email = models.EmailField(null=True, blank=True)
    telefone = models.CharField(max_length=20)
    cpf = models.CharField(max_length=14)
    nascimento = models.DateField()
    rg = models.CharField(max_length=20)
    cep = models.CharField(max_length=8)
    endereco = models.CharField(max_length=200)
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    profissao = models.CharField(max_length=100, default='')
    quantidade_dependentes = models.PositiveIntegerField(default=0)
    recebe_auxilio = models.BooleanField(default=False)
    total_renda = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'))
    observacao_cliente = models.TextField(default='')
    comprovantes = models.OneToOneField('vendas.ComprovantesCliente', on_delete=models.CASCADE, related_name='cliente')
    contato_adicional = models.OneToOneField('vendas.ContatoAdicional', on_delete=models.CASCADE, related_name='cliente', null=True, blank=True)
    informacao_pessoal = models.OneToOneField('vendas.InformacaoPessoal', on_delete=models.CASCADE, related_name='cliente', null=True, blank=True)
    
    def __str__(self):
        return self.nome
    
    def get_absolute_url(self):
        return reverse('vendas:cliente_update', kwargs={'pk': self.pk})
    
    class Meta:
        verbose_name_plural = 'Clientes'

    def save(self, *args, **kwargs):
        self.cpf = re.sub(r'\D', '', self.cpf or '')  # limpa antes de salvar
        super().save(*args, **kwargs)
        


class Venda(Base):
    data_venda = models.DateTimeField(auto_now_add=True)
    cliente = models.ForeignKey('vendas.cliente', on_delete=models.CASCADE, related_name='vendas')
    vendedor = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='vendas_realizadas')
    produtos = models.ManyToManyField('produtos.Produto', through='ProdutoVenda', related_name='vendas')
    caixa = models.ForeignKey('vendas.Caixa', on_delete=models.CASCADE, related_name='vendas')
    observacao = models.TextField(null=True, blank=True)
    repasse_logista = models.DecimalField(max_digits=10, decimal_places=2)
    is_deleted = models.BooleanField(default=False)
    is_trocado = models.BooleanField(default=False)
    
    def qtd_total_parcelas(self):
        return sum(pagamento.parcelas for pagamento in self.pagamentos.filter(tipo_pagamento__parcelas=True))
    
    @cached_property
    def valor_caixa(self):
        return sum(pagamento.valor for pagamento in self.pagamentos.all().filter(tipo_pagamento__caixa=True))

    @property
    def pagamentos_valor_total(self):
        return sum(pagamento.valor for pagamento in self.pagamentos.all().filter(tipo_pagamento__nao_contabilizar=False))
    
    @property
    def pagamentos_valor_total_dinheiro(self):
        return sum(pagamento.valor for pagamento in self.pagamentos.all() if pagamento.tipo_pagamento.caixa)
    
    def calcular_valor_total(self):
        return sum(produto.calcular_valor_total() for produto in self.itens_venda.all())

    def possui_pagamento_bloqueado(self):
        return self.pagamentos.filter(bloqueado=True).exists()

    @cached_property
    def valor_repasse(self):
        return sum(produto.produto.valor_repasse_logista * produto.quantidade for produto in self.itens_venda.all())
    
    @cached_property
    def valor_entrada_cliente(self):
        # Busca o valor de pagamentos do tipo ENTRADA
        entrada_pagamento = self.pagamentos.filter(tipo_pagamento__nome__iexact='ENTRADA').aggregate(total=models.Sum('valor'))['total']
        return entrada_pagamento or 0

    @cached_property
    def lucro_venda(self):
        # print("Calculando lucro da venda...")
        from estoque.models import ProdutoEntrada
        total_lucro = 0
        for produto in self.itens_venda.all():
            # print(f"Produto: {produto.produto.nome}, Quantidade: {produto.quantidade}")
            custo_unitario = ProdutoEntrada.objects.filter(produto=produto.produto).last().custo_unitario
            # print(f"Custo unitário: {custo_unitario}")
            total_lucro += (produto.produto.valor_repasse_logista + produto.produto.entrada_cliente - custo_unitario) * produto.quantidade
            # print(f'Calculo: {produto.produto.valor_repasse_logista} + {produto.produto.entrada_cliente} - {custo_unitario} * {produto.quantidade}')
            # print(f"Lucro parcial: {total_lucro}")
        # print(f"Total lucro: {total_lucro}")
        return total_lucro
    
    @cached_property
    def valor_total_venda(self):
        return sum(pagamento.valor for pagamento in self.pagamentos.all())

    @cached_property
    def custo_total(self):
        from estoque.models import ProdutoEntrada
        total_custo = Decimal('0.00')
        for produto in self.itens_venda.all():
            custo_unitario = ProdutoEntrada.objects.filter(produto=produto.produto).last().custo_unitario
            total_custo += custo_unitario * produto.quantidade
        return total_custo
    
    @cached_property
    def juros(self):
        entrada_pagamento = self.pagamentos.filter(tipo_pagamento__nome__iexact='ENTRADA').aggregate(total=models.Sum('valor'))['total'] or 0
        return sum((self.valor_total_venda - (entrada_pagamento + self.repasse_logista)) * produto.quantidade for produto in self.itens_venda.all())

    def __str__(self):
        return f"{self.cliente} - {self.data_venda.strftime('%d/%m/%Y')}"
    
    def get_absolute_url(self):
        return reverse('vendas:venda_detail', kwargs={'pk': self.pk})
    
    class Meta:
        verbose_name_plural = 'Vendas'
        permissions = (
            ('can_more_desconto', 'Pode dar mais desconto'),
            ('can_generate_report_sale', 'Pode gerar relatório de vendas'),
            ('change_status_analise', 'Pode alterar status de análise'),
            ('can_view_all_sales', 'Pode ver todas as vendas'),
            ('can_view_produtos_vendidos', 'Pode ver aba produtos vendidos'),
            ('can_edit_finished_sale', 'Pode editar venda finalizada'),
            ('can_view_your_dashboard', 'Pode ver seu dashboard'),
            ('can_view_all_dashboard', 'Pode ver todos os dashboards'),
            ('can_generate_dashboard_report', 'Pode gerar relatório de dashboard de todas as lojas'),
            ('view_consulta_serasa', 'Pode visualizar consulta Serasa'),
        )


class AnaliseCreditoCliente(Base):
    STATUS_CHOICES = [
        ('EA', 'Em análise'),
        ('A', 'Aprovado'),
        ('R', 'Reprovado'),
        ('C', 'Cancelado'),   
    ]
    STATUS_APP_CHOICES = [
        ('P', 'Pendente'),
        ('C', 'Confirmação pendente'),
        ('I', 'Instalado'),
    ]
    cliente = models.OneToOneField('vendas.Cliente', on_delete=models.CASCADE, related_name='analise_credito')
    data_analise = models.DateTimeField(auto_now_add=True)
    data_aprovacao = models.DateTimeField(null=True, blank=True)
    data_reprovacao = models.DateTimeField(null=True, blank=True)
    data_cancelamento = models.DateTimeField(null=True, blank=True)
    aprovado_por = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='analises_credito_aprovadas', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='EA')
    status_aplicativo = models.CharField(max_length=20, choices=STATUS_APP_CHOICES, default='P', verbose_name='Status do aplicativo')
    data_pagamento = models.CharField(max_length=20, null=True, blank=True, choices=(
        ('1', 'Dia 1'),
        ('10', 'Dia 10'),
        ('20', 'Dia 20'),
    ), verbose_name='Data de pagamento')
    numero_parcelas = models.CharField(max_length=20, choices=(
        ('4', '4x'),
        ('6', '6x'),
        ('8', '8x'),
        ('10', '10x'),
    ))
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE, related_name='analises_credito')
    imei = models.ForeignKey('estoque.EstoqueImei', on_delete=models.CASCADE, related_name='analises_credito_imei', null=True, blank=True)
    imei_informado = models.CharField(max_length=20, null=True, blank=True, verbose_name='IMEI Informado')
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='analises_credito_venda', null=True, blank=True)
    observacao = models.TextField(null=True, blank=True)
    
    def venda_gerada(self):
        if self.venda:
            return True
        return False
    
    
    def aprovar(self, user):
        self.status = 'A'
        self.data_aprovacao = timezone.now()
        self.aprovado_por = user
        self.save()
        return self.status
    
    def reprovar(self):
        self.status = 'R'
        self.data_reprovacao = timezone.now()
        self.save()
        return self.status
    
    def cancelar(self):
        self.status = 'C'
        self.save()
        return self.status
    
    def __str__(self):
        return f"Análise de crédito para {self.cliente} - {self.data_analise.strftime('%d/%m/%Y')}"
    
    class Meta:
        verbose_name_plural = 'Análises de Crédito'
        permissions = (
            ('can_approve_credit_analysis', 'Pode aprovar análise de crédito'),
            ('can_reject_credit_analysis', 'Pode reprovar análise de crédito'),
            ('can_cancel_credit_analysis', 'Pode cancelar análise de crédito'),
            ('view_all_analise_credito', 'Pode ver todos as análise de crédito')
        )
    
    

class ContatoAdicional(Base):
    nome_adicional = models.CharField(max_length=100, null=True, blank=True)
    contato = models.CharField(max_length=20, null=True, blank=True)
    endereco_adicional = models.CharField(max_length=200, null=True, blank=True)
    obteve_contato = models.BooleanField(default=False)
    

class InformacaoPessoal(Base):
    nome = models.CharField(max_length=100, null=True, blank=True)
    contato = models.CharField(max_length=20, null=True, blank=True)
    endereco = models.CharField(max_length=200, null=True, blank=True)
    obteve_contato = models.BooleanField(default=False)
    

class Endereco(Base):
    cep = models.CharField(max_length=8)
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    endereco = models.CharField(max_length=200)
    numero = models.CharField(max_length=10)
    complemento = models.CharField(max_length=100)
    
    def __str__(self):
        return self.endereco
    
    class Meta:
        verbose_name_plural = 'Informacoes Clientes'

class ComprovantesCliente(Base):
    documento_identificacao_frente = models.FileField(upload_to='comprovantes_clientes', null=True, blank=True)
    documento_identificacao_frente_analise = models.BooleanField(default=False)
    
    documento_identificacao_verso = models.FileField(upload_to='comprovantes_clientes', null=True, blank=True)
    documento_identificacao_verso_analise = models.BooleanField(default=False)
    
    comprovante_residencia = models.FileField(upload_to='comprovantes_clientes', null=True, blank=True)
    comprovante_residencia_analise = models.BooleanField(default=False)
    
    consulta_serasa = models.FileField(upload_to='comprovantes_clientes', null=True, blank=True)
    consulta_serasa_analise = models.BooleanField(default=False)
    restricao = models.BooleanField(default=False)
    
    foto_cliente = models.FileField(upload_to='comprovantes_clientes', null=True, blank=True)
    
    class Meta:
        verbose_name_plural = 'Comprovantes Clientes'

    def __str__(self):
        return f"Comprovantes para {self.cliente.nome if self.cliente else 'Cliente'}"

class ProdutoVenda(Base):
    produto = models.ForeignKey('produtos.Produto', on_delete=models.CASCADE, related_name='produto_vendas')
    imei = models.CharField(max_length=100, null=True, blank=True)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    quantidade = models.PositiveIntegerField()
    valor_desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='itens_venda')
    
    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        
        # Validar se o IMEI não está sendo usado em outra venda
        if self.imei:
            produto_venda_existente = ProdutoVenda.objects.filter(
                imei=self.imei
            ).exclude(pk=self.pk).first()
            
            if produto_venda_existente:
                # Em vez de bloquear, apenas registrar um warning
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f'IMEI {self.imei} já está sendo usado na venda {produto_venda_existente.venda.id}')
    
    def save(self, *args, **kwargs):
        try:
            self.clean()
        except Exception as e:
            # Log do erro mas não interromper a operação
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f'Erro na validação do IMEI {self.imei}: {str(e)}')
        
        super().save(*args, **kwargs)
    

    def calcular_valor_total(self):
        return (self.valor_unitario * self.quantidade) - self.valor_desconto
    
    def lucro(self):
        from estoque.models import ProdutoEntrada
        return ((self.produto.valor_repasse_logista + self.produto.entrada_cliente) - ProdutoEntrada.objects.filter(produto=self.produto).last().custo_unitario) * self.quantidade
    
    def custo(self):
        from estoque.models import ProdutoEntrada
        return ProdutoEntrada.objects.filter(produto=self.produto).last().custo_unitario * self.quantidade
    
    def __str__(self):
        return f"{self.produto.nome} x {self.quantidade} (R$ {self.valor_unitario})"
    
    class Meta:
        verbose_name_plural = 'Produtos Vendas'
        ordering = ['-id']
        permissions = (
            ('can_view_all_products_sold', 'Pode ver todos os produtos vendidos'),
        )
        


class TipoPagamento(Base):
    nome = models.CharField(max_length=100)
    caixa = models.BooleanField(default=False)
    parcelas = models.BooleanField(default=False)
    financeira = models.BooleanField(default=False)
    carne = models.BooleanField(default=False)
    nao_contabilizar = models.BooleanField(default=False)
    
    def __str__(self):
        return self.nome
    
    class  Meta:
        verbose_name_plural = 'Tipos de Pagamentos'
        

class PagamentoQuerySet(models.QuerySet):
    def with_parcelas_info(self):
        # Ignora pagamentos do tipo "entrada"
        return self.exclude(tipo_pagamento__nome__iexact='ENTRADA').annotate(
            total_parcelas=Count('parcelas_pagamento'),
            parcelas_pagas=Count(
                'parcelas_pagamento',
                filter=Q(parcelas_pagamento__pago=True)
            ),
            parcelas_pagas_no_prazo=Count(
                'parcelas_pagamento',
                filter=Q(
                    parcelas_pagamento__pago=True,
                    parcelas_pagamento__data_pagamento__lte=F('parcelas_pagamento__data_vencimento')
                )
            ),
            parcelas_atrasadas=Count(
                'parcelas_pagamento',
                filter=Q(
                    parcelas_pagamento__pago=False,
                    parcelas_pagamento__data_vencimento__lt=timezone.now()
                )
            ),
            next_vencimento=Min(
                'parcelas_pagamento__data_vencimento',
                filter=Q(parcelas_pagamento__pago=False)
            )
        )

    def with_status_flags(self):
        return self.with_parcelas_info().annotate(
            todas_parcelas_pagas=Case(
                When(parcelas_pagas=F('total_parcelas'), then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            ),
            pago_dentro_prazo=Case(
                When(parcelas_pagas_no_prazo=F('total_parcelas'), then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            ),
            com_parcela_atrasada=Case(
                When(parcelas_atrasadas__gt=0, then=Value(True)),
                default=Value(False),
                output_field=BooleanField()
            ),
            com_pagamento_pendente=Case(
                When(
                    Q(parcelas_pagas__lt=F('total_parcelas')) &
                    Q(parcelas_atrasadas=0),
                    then=Value(True)
                ),
                default=Value(False),
                output_field=BooleanField()
            ),
        )
    
    
class StatusPagamento(Base):
    nome = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, editable=False)
    cor_hex = models.CharField(max_length=7, default="#6c757d")  # ex: #FFAA00
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nome)
        super().save(*args, **kwargs)
        
    def __str__(self):
        return self.nome

    class Meta:
        verbose_name_plural = 'Status de Pagamento'


class Pagamento(Base):
    venda = models.ForeignKey('vendas.Venda', on_delete=models.CASCADE, related_name='pagamentos')
    tipo_pagamento = models.ForeignKey('vendas.TipoPagamento', on_delete=models.CASCADE, related_name='pagamentos_tipo')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    parcelas = models.PositiveIntegerField(default=1, null=True, blank=True)
    lembrete = models.BooleanField(default=False)
    # Situações
    bloqueado = models.BooleanField(default=False)
    desativado = models.BooleanField(default=False)
    devolucao = models.BooleanField(default=False)
    quitado = models.BooleanField(default=False)
    sem_contato = models.BooleanField(default=False)
    mais_prazo = models.BooleanField(default=False)
    bo = models.BooleanField(default=False)
    flag_atrasado = models.BooleanField(default=False)
    sem_conexao = models.BooleanField(default=False)
    roubo = models.BooleanField(default=False)
    
    porcentagem_desconto = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    statuses = models.ManyToManyField('vendas.StatusPagamento', related_name='pagamentos', blank=True)
    objects = PagamentoQuerySet.as_manager()
    data_primeira_parcela = models.DateField()
    
    @property
    def valor_parcela(self):
        return self.valor / self.parcelas
    
    def valor_atrasado(self):
        if self.devolucao:
            return 0
        return sum(parcela.valor_restante for parcela in self.parcelas_pagamento.filter(pago=False, data_vencimento__lt=timezone.now()))
    
    def ultimo_vencimento(self):
        # primeiro pagamento em atraso
        # pega a última parcela que não foi paga que tem a data vencimento menor que a data atual e ordena por data de vencimento
        ultimo = self.parcelas_pagamento.filter(pago=False, data_vencimento__lt=timezone.now()).order_by('data_vencimento').last()
        return ultimo.data_vencimento if ultimo else None
    
    def valor_pago_ultimo(self):
        ultimo = self.parcelas_pagamento.filter(pago=True).order_by('data_pagamento').last()
        return ultimo.valor if ultimo else 0
    
    def ultimo_pagamento(self):
        ultimo = self.parcelas_pagamento.filter(pago=True).order_by('-data_pagamento').last()
        return ultimo.data_pagamento if ultimo else None
    
    def valor_a_vencer(self):
        if self.devolucao:
            return 0
        return sum(parcela.valor_restante for parcela in self.parcelas_pagamento.filter(pago=False, data_vencimento__gte=timezone.now()))

    def valor_atual_a_vencer(self):
        if self.devolucao:
            return 0
        proximo = self.parcelas_pagamento.filter(pago=False, data_vencimento__gte=timezone.now()).order_by('data_vencimento').first()
        if proximo:
            return proximo.valor_restante
        return 0

    def proximo_vencimento(self):
        if self.devolucao:
            return None
        proximo = self.parcelas_pagamento.filter(pago=False, data_vencimento__gte=timezone.now()).order_by('data_vencimento').first()
        return proximo.data_vencimento if proximo else None
    
    def valor_total_parcelas(self):
        return sum(parcela.valor for parcela in self.parcelas_pagamento.all())
    
    def parcelas_totais(self):
        return self.parcelas_pagamento.count()

    def parcelas_pagas(self):
        return self.parcelas_pagamento.filter(pago=True).count()
    
    def valor_quitado(self):
        return sum(parcela.valor for parcela in self.parcelas_pagamento.filter(pago=True))
    
    def valor_pendente(self):
        return self.valor - sum(parcela.valor for parcela in self.parcelas_pagamento.filter(pago=True))
    
    def parcelas_pendentes(self):
        if self.devolucao:
            return 0
        return self.parcelas_pagamento.filter(pago=False).count()

    def total_a_vencer(self):
        if self.devolucao:
            return 0
        return sum(parcela.valor_restante for parcela in self.parcelas_pagamento.filter(pago=False))
    
    def total_atrasos(self):
        if self.devolucao:
            return 0
        return sum(parcela.valor_restante for parcela in self.parcelas_pagamento.filter(pago=False, data_vencimento__lt=timezone.now()))
    
    def total_pago(self):
        return sum(parcela.valor for parcela in self.parcelas_pagamento.filter(pago=True))
    
    def __str__(self):
        return f"Pagamento({self.id}) de R$ {self.valor} via {self.tipo_pagamento.nome}"
    
    def get_absolute_url(self):
        return reverse('financeiro:contas_a_receber_update', kwargs={'pk': self.pk})
    
    class Meta:
        verbose_name_plural = 'Pagamentos'
        permissions = (
            ('can_view_all_payments', 'Pode ver todos os pagamentos'),
            ('can_genarate_report_payments', 'Pode gerar relatório de pagamentos'),
            ("can_confirm_quitacao", "Pode confirmar quitação de pagamentos"),
        )
    

class Parcela(Base):
    pagamento = models.ForeignKey('vendas.Pagamento', on_delete=models.CASCADE, related_name='parcelas_pagamento')
    numero_parcela = models.PositiveIntegerField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    tipo_pagamento = models.ForeignKey('vendas.TipoPagamento', on_delete=models.CASCADE, related_name='parcelas_tipo_pagamento', null=True, blank=True)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, default=0)
    data_pagamento = models.DateField(null=True, blank=True)
    data_vencimento = models.DateField()
    pagamento_efetuado = models.BooleanField(default=False)
    pagamento_efetuado_em = models.DateTimeField(null=True, blank=True)
    pago = models.BooleanField(default=False)

    @property
    def valor_restante(self):
        valor_pago = self.valor_pago or 0
        desconto = self.desconto or 0
        return (self.valor - desconto) - valor_pago

    def __str__(self):
        return f"Parcela {self.numero_parcela} de {self.pagamento}"

    class Meta:
        verbose_name_plural = 'Parcelas'
        permissions = (
            ('change_vencimento_parcela', 'Pode alterar data de vencimento de parcelas'),
        )


class Contato(Base):
    cliente = models.ForeignKey('vendas.Cliente', on_delete=models.CASCADE, related_name='contatos')
    data = models.DateField()
    observacao = models.TextField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    modificado_em = models.DateTimeField(auto_now=True)
    criado_por = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='%(class)s_criadas', editable=False, null=True, blank=True)
    modificado_por = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='%(class)s_modificadas', editable=False, null=True, blank=True)

    def __str__(self):
        return self.nome
    
    class Meta:
        verbose_name_plural = 'Contatos'