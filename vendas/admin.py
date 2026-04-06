from django import forms
from django.contrib import admin
from .models import *

class AdminBase(admin.ModelAdmin):
    list_display = ('loja', 'criado_em', 'modificado_em')
    readonly_fields = ('criado_em', 'modificado_em')
    
    def save_model(self, request, obj, form, change):
        obj.save(user=request.user) 
        super().save_model(request, obj, form, change)

class ProdutoVendaInline(admin.TabularInline):
    model = ProdutoVenda
    extra = 1

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.criado_por = request.user
        obj.modificado_por = request.user
        super().save_model(request, obj, form, change)

class PagamentoInline(admin.TabularInline):
    model = Pagamento
    extra = 1

    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.criado_por = request.user
        obj.modificado_por = request.user
        super().save_model(request, obj, form, change)

@admin.register(Venda)
class VendaAdmin(AdminBase):
    list_display = ('data_venda', 'cliente', 'vendedor', 'calcular_valor_total', 'loja')
    search_fields = ('cliente__nome', 'vendedor__first_name', 'vendedor__last_name', 'loja__nome')
    inlines = [ProdutoVendaInline, PagamentoInline]

@admin.register(Pagamento)
class PagamentoAdmin(AdminBase):
    list_display = ('venda', 'tipo_pagamento', 'valor', 'parcelas', 'valor_parcela', 'data_primeira_parcela')
    search_fields = ('venda__cliente__nome', 'venda__vendedor__first_name', 'venda__vendedor__last_name')

@admin.register(TipoPagamento)
class TipoPagamentoAdmin(AdminBase):
    list_display = ('nome', 'caixa', 'parcelas', 'financeira')
    
@admin.register(Caixa)
class CaixaAdmin(AdminBase):
    list_display = ('data_abertura', 'data_fechamento')
    
@admin.register(ProdutoVenda)
class ProdutoVendaAdmin(admin.ModelAdmin):
    list_display = ('produto', 'quantidade', 'venda', 'loja')
    list_filter = ('loja',)
    search_fields = ('produto__nome',)


@admin.register(Cliente)
class ClienteAdmin(AdminBase):
    list_display = ('nome', 'email', 'telefone', 'cpf')
    list_filter = ('loja',)

@admin.register(Endereco)
class EnderecoAdmin(AdminBase):
    list_display = ('numero', 'bairro', 'cidade', 'cep')

@admin.register(ComprovantesCliente)
class ComprovantesClienteAdmin(AdminBase):
    pass 


@admin.register(Loja)
class LojaAdmin(AdminBase):
    list_display = ('nome', 'cnpj', 'telefone', 'pode_vender_iphone')
    
    def get_readonly_fields(self, request, obj=None):
        readonly_fields = super().get_readonly_fields(request, obj)
        # Apenas ADMINISTRADOR pode editar pode_vender_iphone
        if not request.user.is_superuser and not request.user.groups.filter(name='ADMINISTRADOR').exists():
            readonly_fields = list(readonly_fields) + ['pode_vender_iphone']
        return readonly_fields
    
    
@admin.register(Parcela)
class ParcelaAdmin(AdminBase):
    list_display = ('pagamento', 'valor', 'data_vencimento', 'pago')


@admin.register(LancamentoCaixa)
class LancamentoCaixaAdmin(AdminBase):
    list_display = ('caixa', 'tipo_lancamento', 'valor')
    
    
@admin.register(AnaliseCreditoCliente)
class AnaliseCreditoClienteAdmin(AdminBase):
    list_display = ('cliente', 'status', 'data_analise', 'loja')
    list_filter = ('status', 'loja',)
    search_fields = ('cliente__nome', 'loja__nome')
    list_editable = ('status',)


@admin.register(StatusPagamento)
class StatusPagamentoAdmin(AdminBase):
    list_display = ('nome', 'slug', 'cor_hex')
    search_fields = ('nome',)
    list_editable = ('cor_hex',)


class NumeroAutenticadorForm(forms.ModelForm):
    numero = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'vTextField',
            'placeholder': '(00) 00000-0000',
            'data-mask': '(00) 00000-0000',
        }),
        label='Número de Telefone',
    )

    class Meta:
        model = NumeroAutenticador
        fields = '__all__'


@admin.register(NumeroAutenticador)
class NumeroAutenticadorAdmin(AdminBase):
    form = NumeroAutenticadorForm
    list_display = ('numero', 'descricao', 'ativo', 'loja')
    list_filter = ('ativo', 'loja')
    search_fields = ('numero', 'descricao')
    list_editable = ('ativo',)

    class Media:
        js = ('admin/js/numero_autenticador_mask.js',)