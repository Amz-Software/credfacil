from django.contrib import admin

from produtos.models import Produto
from .models import *
from django.contrib import messages

# Register your models here.


class AdminBase(admin.ModelAdmin):
    list_display = ('loja', 'criado_em', 'modificado_em', 'criado_por', 'modificado_por')
    readonly_fields = ('criado_em', 'modificado_em', 'criado_por', 'modificado_por')
    
    def save_model(self, request, obj, form, change):
        obj.save(user=request.user) 
        super().save_model(request, obj, form, change)


@admin.register(EntradaEstoque)
class EntradaEstoqueAdmin(AdminBase):
  pass


@admin.register(Estoque)
class EstoqueAdmin(AdminBase):
  list_display = ('produto', 'quantidade_disponivel') + AdminBase.list_display
  search_fields = ('produto__nome',)
  list_filter = ('produto',)
  actions = ['trocar_para_credfacil']
  
  def trocar_para_credfacil(self, request, queryset):
      for entrada in queryset:
          nome = entrada.produto.nome
          try:
              novo = Produto.objects.get(nome__icontains=nome, loja__credfacil=True)
          except Produto.DoesNotExist:
              self.message_user(
                  request,
                  f"Produto CredFácil não encontrado p/ '{nome}'",
                  level=messages.ERROR
              )
              continue
          entrada.produto = novo
          entrada.save()
      self.message_user(request, "Produtos trocados para CredFácil com sucesso.")


@admin.register(Fornecedor)
class FornecedorAdmin(AdminBase):
  list_display = ('nome', 'telefone', 'email') + AdminBase.list_display
  search_fields = ('nome', 'telefone', 'email')
  list_filter = ('nome',)
  

@admin.register(ProdutoEntrada)
class ProdutoEntradaAdmin(AdminBase):
  list_display = ('entrada', 'produto', 'imei', 'custo_unitario', 'quantidade', 'custo_total') + AdminBase.list_display
  search_fields = ('produto__nome', 'imei')
  list_filter = ('entrada', 'produto')
  actions = ['trocar_para_credfacil']

  def trocar_para_credfacil(self, request, queryset):
      for entrada in queryset:
          nome = entrada.produto.nome
          try:
              novo = Produto.objects.get(nome__icontains=nome, loja__credfacil=True)
          except Produto.DoesNotExist:
              self.message_user(
                  request,
                  f"Produto CredFácil não encontrado p/ '{nome}'",
                  level=messages.ERROR
              )
              continue
          entrada.produto = novo
          entrada.save()
      self.message_user(request, "Produtos trocados para CredFácil com sucesso.")
  trocar_para_credfacil.short_description = "Trocar produto para loja CredFácil"
  
@admin.register(EstoqueImei)
class EstoqueImeiAdmin(AdminBase):
  list_display = ('produto', 'imei', 'vendido') + AdminBase.list_display
  search_fields = ('produto__nome', 'imei')
  list_filter = ('produto', 'vendido')
  actions = ['trocar_para_credfacil']
  
  
  def trocar_para_credfacil(self, request, queryset):
      for entrada in queryset:
          nome = entrada.produto.nome
          try:
              novo = Produto.objects.get(nome__icontains=nome, loja__credfacil=True)
          except Produto.DoesNotExist:
              self.message_user(
                  request,
                  f"Produto CredFácil não encontrado p/ '{nome}'",
                  level=messages.ERROR
              )
              continue
          entrada.produto = novo
          entrada.save()
      self.message_user(request, "Produtos trocados para CredFácil com sucesso.")
  trocar_para_credfacil.short_description = "Trocar produto para loja CredFácil"
  