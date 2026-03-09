from django.contrib import admin

# Register your models here.
from .models import CorProduto, EstadoProduto, Fabricante, MemoriaProduto, Produto, TipoProduto, Marca

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

from django import forms
from django.utils.html import format_html

class MarcaAdminForm(forms.ModelForm):
    class Meta:
        model = Marca
        fields = '__all__'
        widgets = {
            'cor': forms.TextInput(attrs={
                'type': 'color', 
                'style': 'height: 40px; width: 60px; padding: 0; cursor: pointer; border: none; background: none; border-radius: 4px;'
            }),
        }

@admin.register(Marca)
class MarcaAdmin(AdminBase):
    form = MarcaAdminForm
    list_display = ('nome', 'cor_preview', 'icone_preview')
    search_fields = ('nome',)

    def cor_preview(self, obj):
        if not obj.cor:
            return "N/A"
        return format_html(
            '<div style="width: 25px; height: 25px; background-color: {}; border-radius: 5px; border: 1px solid #ccc; display: inline-block; vertical-align: middle;" title="{}"></div>',
            obj.cor, obj.cor
        )
    cor_preview.short_description = 'Cor'
    
    def icone_preview(self, obj):
        if not obj.icone:
            return "N/A"
        return format_html('<i class="{}" style="font-size: 20px; vertical-align: middle;"></i> ({})', obj.icone, obj.get_icone_display() if hasattr(obj, 'get_icone_display') else obj.icone)
    icone_preview.short_description = 'Ícone'
