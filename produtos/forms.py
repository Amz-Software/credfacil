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
            'valor': 'Valor Base',
            'entrada_cliente': 'Entrada Mínima',
            'tipo': 'Tipo',
            'marca': 'Marca',
        }
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'disabled': 'disabled'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control'}),
            'entrada_cliente': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'marca': forms.Select(attrs={'class': 'form-control'}),
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


class MarcaForms(forms.ModelForm):
    class Meta:
        model = Marca
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'nome': 'Nome',
            'cor': 'Cor de Destaque',
            'icone': 'Ícone',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'cor': forms.TextInput(attrs={
                'type': 'color', 
                'class': 'form-control form-control-color p-1', 
                'style': 'height: 40px; cursor: pointer;'
            }),
            'icone': forms.Select(attrs={'class': 'form-select'}),
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


class ParcelamentoForms(forms.ModelForm):
    class Meta:
        model = Parcelamento
        fields = '__all__'
        exclude = ['loja', 'criado_por', 'modificado_por']
        labels = {
            'marca': 'Marca',
            'qtd_vezes': 'Quantidade de Vezes',
            'porcentagem_juros': 'Porcentagem de Juros (%)',
        }
        widgets = {
            'marca': forms.Select(attrs={'class': 'form-control'}),
            'qtd_vezes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'porcentagem_juros': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
        }

    def __init__(self, *args, disabled=False, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if disabled:
            for field in self.fields.values():
                field.widget.attrs['disabled'] = True

    def clean(self):
        cleaned_data = super().clean()
        marca = cleaned_data.get('marca')
        qtd_vezes = cleaned_data.get('qtd_vezes')
        if marca and qtd_vezes is not None:
            qs = Parcelamento.objects.filter(marca=marca, qtd_vezes=qtd_vezes)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f"Já existe um parcelamento de {qtd_vezes}x cadastrado para a marca {marca}."
                )
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            if not instance.pk:
                instance.criado_por = self.user
            instance.modificado_por = self.user
        if commit:
            instance.save()
        return instance
