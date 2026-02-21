from typing import Any
from django import forms

from produtos.models import *


class ProdutoForms(forms.ModelForm):
    is_iphone = forms.TypedChoiceField(
        choices=[('False', 'Não'), ('True', 'Sim')],
        coerce=lambda v: v == 'True',
        label='É iPhone?',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_is_iphone'}),
        initial='False',
    )

    class Meta:
        model = Produto
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por', 'ativo']
        labels = {
            'codigo': 'Código',
            'nome': 'Nome',
            'valor': 'Valor base (iPhone)',
            'valor_repasse_logista': 'Valor Repasse Logista',
            'entrada_cliente': 'Entrada Cliente',
            'valor_8_vezes': 'Valor total 8X',
            'valor_6_vezes': 'Valor total 6X',
            'valor_4_vezes': 'Valor total 4X',
            'valor_10_vezes': 'Valor total 10X',
            'valor_12_vezes': 'Valor total 12X',
            'valor_14_vezes': 'Valor total 14X',
            'tipo': 'Tipo',
            'fabricante': 'Fabricante',
            'cor': 'Cor',
            'memoria': 'Memória',
            'estado': 'Estado',
        }
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'disabled': 'disabled'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control'}),
            'valor_repasse_logista': forms.TextInput(attrs={'class': 'form-control'}),
            'entrada_cliente': forms.TextInput(attrs={'class': 'form-control'}),
            'valor_8_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'valor_6_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'valor_4_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'valor_10_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'valor_12_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'valor_14_vezes': forms.TextInput(attrs={'class': 'form-control', 'oninput': 'updateValues()'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'fabricante': forms.Select(attrs={'class': 'form-control'}),
            'cor': forms.Select(attrs={'class': 'form-control'}),
            'memoria': forms.Select(attrs={'class': 'form-control'}),
            'estado': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True


    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:  
            if not instance.pk: 
                instance.criado_por = self.user
            instance.modificado_por = self.user 
        if commit:
            instance.save()
        return instance
    
class CorProdutoForms(forms.ModelForm):
    class Meta:
        model = CorProduto
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)  # Pega o usuário que será passado pela view
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:  
            if not instance.pk: 
                instance.criado_por = self.user
            instance.modificado_por = self.user 
        if commit:
            instance.save()
        return instance
    
class TipoForms(forms.ModelForm):
    class Meta:
        model = TipoProduto
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)  # Pega o usuário que será passado pela view
        # caso o usario tenha permissao mostrar o campo assistencia
        super().__init__(*args, **kwargs)
        if self.user and self.user.has_perm('assistencia.view_assistencia'):
            self.fields['assistencia'].widget.attrs['disabled'] = False
        else:
            self.fields['assistencia'].widget.attrs['disabled'] = True
        # caso o usuario tenha permissao mostrar o campo assistencia
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:  
            if not instance.pk: 
                instance.criado_por = self.user
            instance.modificado_por = self.user 
        if commit:
            instance.save()
        return instance
    
class FabricanteForms(forms.ModelForm):
    class Meta:
        model = Fabricante
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)  # Pega o usuário que será passado pela view
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:  
            if not instance.pk: 
                instance.criado_por = self.user
            instance.modificado_por = self.user 
        if commit:
            instance.save()
        return instance
    
class MemoriaForms(forms.ModelForm):
    class Meta:
        model = MemoriaProduto
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)  # Pega o usuário que será passado pela view
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:  
            if not instance.pk: 
                instance.criado_por = self.user
            instance.modificado_por = self.user 
        if commit:
            instance.save()
        return instance
    
class EstadoProdutoForms(forms.ModelForm):
    class Meta:
        model = EstadoProduto
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)  # Pega o usuário que será passado pela view
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            if not instance.pk:
                instance.criado_por = self.user
            instance.modificado_por = self.user
        if commit:
            instance.save()
        return instance


class ParcelamentoForms(forms.ModelForm):
    class Meta:
        model = Parcelamento
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'qtd_vezes': 'Quantidade de Vezes',
            'porcentagem_juros': 'Porcentagem de Juros (%)',
        }
        widgets = {
            'qtd_vezes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'porcentagem_juros': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            if not instance.pk:
                instance.criado_por = self.user
            instance.modificado_por = self.user
        if commit:
            instance.save()
        return instance
