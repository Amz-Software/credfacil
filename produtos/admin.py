from django.contrib import admin

# Register your models here.
from .models import CorProduto, EstadoProduto, Fabricante, MemoriaProduto, Produto, TipoProduto

class AdminBase(admin.ModelAdmin):
    list_display = ('criado_em', 'modificado_em', 'criado_por', 'modificado_por')
    readonly_fields = ('criado_em', 'modificado_em', 'criado_por', 'modificado_por')
    
    def save_model(self, request, obj, form, change):
        obj.save(user=request.user)  # Passa o usuário para o método save
        super().save_model(request, obj, form, change)

@admin.register(CorProduto)
class CorProdutoAdmin(AdminBase):
    pass

@admin.register(EstadoProduto)
class EstadoProdutoAdmin(AdminBase):
    pass

@admin.register(Fabricante)
class FabricanteAdmin(AdminBase):
    pass

@admin.register(MemoriaProduto)
class MemoriaProdutoAdmin(AdminBase):
    pass

@admin.register(Produto)
class ProdutoAdmin(AdminBase):
    list_display = ('nome', 'loja', 'ativo')
    search_fields = ('nome',)

@admin.register(TipoProduto)
class TipoProdutoAdmin(AdminBase):
    pass

