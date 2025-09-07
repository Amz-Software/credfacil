from django import forms
from django.db.models import OuterRef, Exists
from accounts.models import User
from estoque.models import Estoque, EstoqueImei
from produtos.models import Produto
from .models import *
from django_select2.forms import Select2Widget, ModelSelect2Widget, Select2MultipleWidget
from django_select2.forms import ModelSelect2MultipleWidget, HeavySelect2Widget
from collections import OrderedDict


class ProdutoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # aqui você define exatamente como quer que apareça cada opção
        return f"{obj.nome} – Entrada: R$ {obj.entrada_cliente}"

class EstoqueImeiSelectWidgetEdit(HeavySelect2Widget):
    data_view = 'estoque:estoque-imei-search-edit'
    
    def render(self, name, value, attrs=None, renderer=None):
        # Se houver um valor, insere a opção inicial no HTML
        initial_options = []
        if value:
            try:
                imei_obj = self.get_queryset().get(pk=value)
                # Monta o texto da opção igual ao utilizado na view de busca
                text = f'{imei_obj.imei} - {imei_obj.produto.nome} - {imei_obj.vendido}'
                initial_options = [(imei_obj.pk, text)]
                # Se desejar, pode inserir também um atributo no select para uso no JS:
                if attrs is None:
                    attrs = {}
                attrs['data-initial-text'] = text
            except Exception:
                initial_options = [(value, value)]
        
        # Armazena as opções originais (se houver)
        original_choices = list(self.choices)
        # Mescla a opção inicial com as demais
        choices = initial_options + original_choices
        self.choices = choices
        rendered = super().render(name, value, attrs, renderer)
        # Restaura as opções originais para evitar efeitos colaterais
        self.choices = original_choices
        return rendered

class EstoqueImeiSelectWidget(HeavySelect2Widget):
    data_view = 'estoque:estoque-imei-search'


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'
        exclude = ['comprovantes', 'contato_adicional', 'informacao_pessoal','loja']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control tel'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control cpf'}),
            'nascimento': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'},
                format='%Y-%m-%d'
            ),
            'rg': forms.TextInput(attrs={'class': 'form-control rg'}),
            'cep': forms.TextInput(attrs={'class': 'form-control cep'}),
            'bairro': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'cidade': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'nome': 'Nome*',
            'telefone': 'Telefone*',
            'cpf': 'CPF*',
            'nascimento': 'Data de Nascimento*',
            'rg': 'RG*',
            'cep': 'CEP*',
            'bairro': 'Bairro*',
            'endereco': 'Endereço*',
            'cidade': 'Cidade*',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ['email']:
                field.required = True
                
        if self.instance and self.instance.pk:
            if user and not user.has_perm('vendas.can_edit_finished_sale'):
                if not self.instance.analise_credito.status == 'EA':
                    self.fields['nome'].disabled = True
                    self.fields['email'].disabled = True
                    self.fields['telefone'].disabled = True
                    self.fields['cpf'].disabled = True
                    self.fields['nascimento'].disabled = True
                    self.fields['rg'].disabled = True
                    self.fields['cep'].disabled = True
                    self.fields['bairro'].disabled = True
                    self.fields['endereco'].disabled = True
                    self.fields['cidade'].disabled = True
            
            if user and not user.has_perm('vendas.change_status_analise'):
                self.fields['nome'].disabled = True
                self.fields['email'].disabled = True
                self.fields['telefone'].disabled = True
                self.fields['cpf'].disabled = True
                self.fields['nascimento'].disabled = True
                self.fields['rg'].disabled = True
                self.fields['cep'].disabled = True
                self.fields['bairro'].disabled = True
                self.fields['endereco'].disabled = True
                self.fields['cidade'].disabled = True

    def clean_telefone(self):
        telefone = self.cleaned_data.get('telefone')
        if telefone:
            telefone = telefone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not telefone.isdigit():
                raise forms.ValidationError("Telefone deve conter apenas números.")
            if len(telefone) < 10 or len(telefone) > 11:
                raise forms.ValidationError("Telefone deve ter entre 10 e 11 dígitos.")
        return telefone
    
    def clean_cpf(self):
        cpf = self.cleaned_data.get('cpf')
        if cpf:
            cpf = cpf.replace('.', '').replace('-', '')
            if not cpf.isdigit():
                raise forms.ValidationError("CPF deve conter apenas números.")
            if len(cpf) != 11:
                raise forms.ValidationError("CPF deve ter exatamente 11 dígitos.")
        return cpf

    def clean_rg(self):
        rg = self.cleaned_data.get('rg')
        if rg:
            rg = rg.replace('.', '').replace('-', '')
            if not rg.isdigit():
                raise forms.ValidationError("RG deve conter apenas números.")
            if len(rg) < 7 or len(rg) > 12:
                raise forms.ValidationError("RG deve ter entre 7 e 12 dígitos.")
        return rg
    
    def clean_cep(self):
        cep = self.cleaned_data.get('cep')
        if cep:
            cep = cep.replace('-', '').replace('.', '')
            if not cep.isdigit():
                raise forms.ValidationError("CEP deve conter apenas números.")
            if len(cep) != 8:
                raise forms.ValidationError("CEP deve ter exatamente 8 dígitos.")
        return cep
    
class ClienteTelefoneForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'
        exclude = ['comprovantes', 'contato_adicional', 'informacao_pessoal','loja']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control tel'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'nascimento': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'},
                format='%Y-%m-%d'
            ),
            'rg': forms.TextInput(attrs={'class': 'form-control'}),
            'cep': forms.TextInput(attrs={'class': 'form-control'}),
            'bairro': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'cidade': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'nome': 'Nome*',
            'telefone': 'Telefone*',
            'cpf': 'CPF*',
            'nascimento': 'Data de Nascimento*',
            'rg': 'RG*',
            'cep': 'CEP*',
            'bairro': 'Bairro*',
            'endereco': 'Endereço*',
            'cidade': 'Cidade*',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            print(name, field)
            if name == 'telefone':
                field.required = True
                field.disabled = False
            else:
                field.required = False
                field.disabled = True


class ContatoAdicionalForm(forms.ModelForm):
    obteve_contato = forms.ChoiceField(
        label='Obteve Contato',
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Sim'), (False, 'Não')]
    )
    class Meta:
        model = ContatoAdicional
        fields = '__all__'
        exclude = ['cliente', 'loja']
        widgets = {
            'nome_adicional': forms.TextInput(attrs={'class': 'form-control'}),
            'contato': forms.TextInput(attrs={'class': 'form-control tel'}),
            'endereco_adicional': forms.TextInput(attrs={'class': 'form-control'}),
            'obteve_contato': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ['email']:
                field.required = True
        
        if not self.instance and user and not user.has_perm('vendas.change_status_analise'):
            self.fields.pop('obteve_contato', None)
                
        if self.instance and self.instance.pk:
            if user and not user.has_perm('vendas.change_status_analise'):
                self.fields['nome_adicional'].disabled = True
                self.fields['contato'].disabled = True
                self.fields['endereco_adicional'].disabled = True
                self.fields['obteve_contato'].disabled = True
                
            if user and not user.has_perm('vendas.can_edit_finished_sale'):
                if not self.instance.cliente.analise_credito.status == 'EA':
                    self.fields['nome_adicional'].disabled = True
                    self.fields['endereco_adicional'].disabled = True
                    self.fields['obteve_contato'].disabled = True
                    if self.instance.cliente.analise_credito.venda:
                        self.fields['contato'].disabled = True

    def clean_contato(self):
        contato = self.cleaned_data.get('contato')
        if contato:
            contato = contato.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not contato.isdigit():
                raise forms.ValidationError("Contato deve conter apenas números.")
            if len(contato) < 10 or len(contato) > 11:
                raise forms.ValidationError("Contato deve ter entre 10 e 11 dígitos.")
        return contato
    
    
class ContatoAdicionalEditForm(forms.ModelForm):
    obteve_contato = forms.ChoiceField(
        label='Obteve Contato',
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Sim'), (False, 'Não')]
    )
    class Meta:
        model = ContatoAdicional
        fields = '__all__'
        exclude = ['cliente', 'loja']
        widgets = {
            'nome_adicional': forms.TextInput(attrs={'class': 'form-control'}),
            'contato': forms.TextInput(attrs={'class': 'form-control tel'}),
            'endereco_adicional': forms.TextInput(attrs={'class': 'form-control'}),
            'obteve_contato': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.disabled = True

    def clean_contato(self):
        contato = self.cleaned_data.get('contato')
        if contato:
            contato = contato.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not contato.isdigit():
                raise forms.ValidationError("Contato deve conter apenas números.")
            if len(contato) < 10 or len(contato) > 11:
                raise forms.ValidationError("Contato deve ter entre 10 e 11 dígitos.")
        return contato

class InformacaoPessoalForm(forms.ModelForm):
    nome_pessoal = forms.CharField(label='Nome', widget=forms.TextInput(attrs={'class': 'form-control'}))
    contato_pessoal = forms.CharField(label='Contato', widget=forms.TextInput(attrs={'class': 'form-control tel'}))
    endereco_pessoal = forms.CharField(label='Endereço', widget=forms.TextInput(attrs={'class': 'form-control'}))
    obteve_contato_pessoal = forms.ChoiceField(
        label='Obteve Contato',
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Sim'), (False, 'Não')]
    )

    class Meta:
        model = InformacaoPessoal
        fields = '__all__'
        exclude = ['cliente', 'loja', 'nome', 'contato', 'endereco', 'obteve_contato']
        
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        self.fields['nome_pessoal'].initial = self.instance.nome
        self.fields['contato_pessoal'].initial = self.instance.contato
        self.fields['endereco_pessoal'].initial = self.instance.endereco
        self.fields['obteve_contato_pessoal'].initial = self.instance.obteve_contato
        
        if not self.instance and user and not user.has_perm('vendas.change_status_analise'):
            self.fields.pop('obteve_contato_pessoal', None)
                
        if self.instance and self.instance.pk:
            if user and not user.has_perm('vendas.change_status_analise'):
                self.fields['nome_pessoal'].disabled = True
                self.fields['contato_pessoal'].disabled = True
                self.fields['endereco_pessoal'].disabled = True
                self.fields['obteve_contato_pessoal'].disabled = True
                
            if user and not user.has_perm('vendas.can_edit_finished_sale'):
                if not self.instance.cliente.analise_credito.status == 'EA':
                    self.fields['nome_pessoal'].disabled = True
                    # self.fields['contato_pessoal'].disabled = True
                    self.fields['endereco_pessoal'].disabled = True
                    self.fields['obteve_contato_pessoal'].disabled = True
                    if self.instance.cliente.analise_credito.venda:
                        self.fields['contato_pessoal'].disabled = True

    def clean_contato_pessoal(self):
        contato = self.cleaned_data.get('contato_pessoal')
        if contato:
            contato = contato.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not contato.isdigit():
                raise forms.ValidationError("Contato deve conter apenas números.")
            if len(contato) < 10 or len(contato) > 11:
                raise forms.ValidationError("Contato deve ter entre 10 e 11 dígitos.")
        return contato
        
    def save(self, commit=True):
        self.instance.nome = self.cleaned_data.get('nome_pessoal')
        self.instance.contato = self.cleaned_data.get('contato_pessoal')
        self.instance.endereco = self.cleaned_data.get('endereco_pessoal')
        self.instance.obteve_contato = self.cleaned_data.get('obteve_contato_pessoal')
        return super().save(commit=commit)
    
class InformacaoPessoalEditForm(forms.ModelForm):
    nome_pessoal = forms.CharField(label='Nome', widget=forms.TextInput(attrs={'class': 'form-control'}))
    contato_pessoal = forms.CharField(label='Contato', widget=forms.TextInput(attrs={'class': 'form-control tel'}))
    endereco_pessoal = forms.CharField(label='Endereço', widget=forms.TextInput(attrs={'class': 'form-control'}))
    obteve_contato_pessoal = forms.ChoiceField(
        label='Obteve Contato',
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Sim'), (False, 'Não')]
    )

    class Meta:
        model = InformacaoPessoal
        fields = '__all__'
        exclude = ['cliente', 'loja', 'nome', 'contato', 'endereco', 'obteve_contato']
        
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.disabled = True
        
    def save(self, commit=True):
        self.instance.nome = self.cleaned_data.get('nome_pessoal')
        self.instance.contato = self.cleaned_data.get('contato_pessoal')
        self.instance.endereco = self.cleaned_data.get('endereco_pessoal')
        self.instance.obteve_contato = self.cleaned_data.get('obteve_contato_pessoal')
        return super().save(commit=commit)

    def clean_contato_pessoal(self):
        contato = self.cleaned_data.get('contato_pessoal')
        if contato:
            contato = contato.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
            if not contato.isdigit():
                raise forms.ValidationError("Contato deve conter apenas números.")
            if len(contato) < 10 or len(contato) > 11:
                raise forms.ValidationError("Contato deve ter entre 10 e 11 dígitos.")
        return contato



class AnaliseCreditoClienteForm(forms.ModelForm):
    produto = ProdutoChoiceField(
        queryset=Produto.objects.all(),
        widget=Select2Widget(attrs={'class': 'form-control'}),
        label='Produto'
    )
    class Meta:
        model = AnaliseCreditoCliente
        fields = ['produto','data_pagamento','numero_parcelas', 'observacao']
        widgets = {
            'data_pagamento': forms.Select(attrs={'class': 'form-control'}),
            'numero_parcelas': forms.Select(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Tornar o campo observacao obrigatório
        self.fields['observacao'].required = True
        self.fields['observacao'].widget.attrs['required'] = 'required'
        
        if self.instance and self.instance.pk:
            # Verifica se o usuário é analista
            is_analista = user and user.groups.filter(name='ANALISTA').exists()
            
            # Verifica se a venda já foi gerada
            venda_gerada = self.instance.venda is not None
            
            if user and not user.has_perm('vendas.change_status_analise') and not is_analista:
                # if self.instance.status == 'EA':
                self.fields['produto'].disabled = True
                self.fields['numero_parcelas'].disabled = True
                self.fields['data_pagamento'].disabled = True
            
            # Se a venda foi gerada, apenas usuários com permissão específica podem editar
            if venda_gerada:
                if not user.has_perm('vendas.can_edit_finished_sale'):
                    self.fields['produto'].disabled = True
                    self.fields['numero_parcelas'].disabled = True
                    self.fields['data_pagamento'].disabled = True
                    self.fields['observacao'].disabled = True
            # Se a venda não foi gerada, analistas podem editar tudo
            elif not venda_gerada and is_analista:
                # Analistas podem editar tudo antes da venda ser gerada
                self.fields['produto'].disabled = False
                self.fields['numero_parcelas'].disabled = False
                self.fields['data_pagamento'].disabled = False
                self.fields['observacao'].disabled = False
class AnaliseCreditoClienteImeiForm(forms.ModelForm):
    produto = ProdutoChoiceField(
        queryset=Produto.objects.all(),
        widget=Select2Widget(attrs={'class': 'form-control'}),
        label='Produto'
    )
    class Meta:
        model = AnaliseCreditoCliente
        fields = ['produto','data_pagamento','numero_parcelas', 'imei', 'observacao']
        widgets = {
            'data_pagamento': forms.Select(attrs={'class': 'form-control'}),
            'numero_parcelas': forms.Select(attrs={'class': 'form-control'}),
            'imei': EstoqueImeiSelectWidget(
                max_results=10,
                attrs={
                    'class': 'form-control',
                    'data-minimum-input-length': '0',
                    'data-placeholder': 'Selecione um IMEI',
                    'data-allow-clear': 'true',
                }
            ),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Tornar o campo observacao obrigatório
        self.fields['observacao'].required = True
        self.fields['observacao'].widget.attrs['required'] = 'required'

        # Desabilita todos os campos, exceto 'imei'
        for field_name in ['produto', 'data_pagamento', 'numero_parcelas', 'observacao']:
            self.fields[field_name].disabled = True
        # 'imei' permanece habilitado



class ComprovantesClienteForm(forms.ModelForm):
    restricao = forms.ChoiceField(
        label='Restrição',
        required=None,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Com Restrição'), (False, 'Sem Restrição')]
    )
    class Meta:
        model = ComprovantesCliente
        exclude = ['cliente', 'loja']
        widgets = {
            'documento_identificacao_frente': forms.FileInput(attrs={'class': 'form-control'}),
            'documento_identificacao_frente_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'documento_identificacao_verso': forms.FileInput(attrs={'class': 'form-control'}),
            'documento_identificacao_verso_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'comprovante_residencia': forms.FileInput(attrs={'class': 'form-control'}),
            'comprovante_residencia_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'consulta_serasa': forms.FileInput(attrs={'class': 'form-control'}),
            'consulta_serasa_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'foto_cliente': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'documento_identificacao_frente': 'Documento de Identificação Frente*',
            'documento_identificacao_frente_analise': 'Análise Documento de Identificação Frente',
            'documento_identificacao_verso': 'Documento de Identificação Verso*',
            'documento_identificacao_verso_analise': 'Análise Documento de Identificação Verso',
            'comprovante_residencia': 'Comprovante de Residência*',
            'comprovante_residencia_analise': 'Análise Comprovante de Residência',
            'consulta_serasa': 'Consulta Serasa',
            'consulta_serasa_analise': 'Análise Consulta Serasa',
            'restricao': 'Restrição',
            'foto_cliente': 'Foto do Cliente*',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Se não tiver permissão para alterar status de análise E não tiver permissão para visualizar consulta Serasa
        if not (user and (user.has_perm('vendas.change_status_analise') or user.has_perm('vendas.view_consulta_serasa'))):
            self.fields.pop('consulta_serasa', None)
            self.fields.pop('consulta_serasa_analise', None)
            self.fields.pop('restricao', None)

        # 1) Se não tiver permissão, remove todos os campos que terminam em "_analise"
        if not (user and user.has_perm('vendas.view_all_analise_credito')):
            for name in list(self.fields):
                if name.endswith('_analise'):
                    self.fields.pop(name)

        # 2) Inicializa as checkboxes (se elas existirem)
        for analise_field in (
            'documento_identificacao_frente_analise',
            'documento_identificacao_verso_analise',
            'comprovante_residencia_analise',
            'consulta_serasa_analise',
            'restricao',
        ):
            if analise_field in self.fields:
                self.fields[analise_field].initial = False

        # 3) Torna obrigatórios todos os outros campos (mesmo lógica que você já tinha)
        exceptions = {
            'consulta_serasa',
            'consulta_serasa_analise',
            'documento_identificacao_frente_analise',
            'documento_identificacao_verso_analise',
            'comprovante_residencia_analise',
        }
        for name, field in self.fields.items():
            if name not in exceptions:
                field.required = True
        
        if self.instance and self.instance.pk:
            if user and not user.has_perm('vendas.change_status_analise'):
                self.fields['documento_identificacao_frente'].disabled = True
                self.fields['documento_identificacao_verso'].disabled = True
                self.fields['comprovante_residencia'].disabled = True
                self.fields['foto_cliente'].disabled = True
            
            if user and not user.has_perm('vendas.can_edit_finished_sale'):
                if self.instance.cliente.analise_credito and  not self.instance.cliente.analise_credito.status == 'EA':
                    self.fields['documento_identificacao_frente'].disabled = True
                    self.fields['documento_identificacao_verso'].disabled = True
                    self.fields['comprovante_residencia'].disabled = True
                    self.fields['consulta_serasa'].disabled = True
                    self.fields['foto_cliente'].disabled = True
                    
                    
class ComprovantesClienteEditForm(forms.ModelForm):
    restricao = forms.ChoiceField(
        label='Restrição',
        required=None,
        widget=forms.Select(attrs={'class': 'form-control'}),
        choices=[(True, 'Com Restrição'), (False, 'Sem Restrição')]
    )
    class Meta:
        model = ComprovantesCliente
        exclude = ['cliente', 'loja']
        widgets = {
            'documento_identificacao_frente': forms.FileInput(attrs={'class': 'form-control'}),
            'documento_identificacao_frente_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'documento_identificacao_verso': forms.FileInput(attrs={'class': 'form-control'}),
            'documento_identificacao_verso_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'comprovante_residencia': forms.FileInput(attrs={'class': 'form-control'}),
            'comprovante_residencia_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'consulta_serasa': forms.FileInput(attrs={'class': 'form-control'}),
            'consulta_serasa_analise': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'foto_cliente': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'documento_identificacao_frente': 'Documento de Identificação Frente*',
            'documento_identificacao_frente_analise': 'Análise Documento de Identificação Frente',
            'documento_identificacao_verso': 'Documento de Identificação Verso*',
            'documento_identificacao_verso_analise': 'Análise Documento de Identificação Verso',
            'comprovante_residencia': 'Comprovante de Residência*',
            'comprovante_residencia_analise': 'Análise Comprovante de Residência',
            'consulta_serasa': 'Consulta Serasa',
            'consulta_serasa_analise': 'Análise Consulta Serasa',
            'restricao': 'Restrição',
            'foto_cliente': 'Foto do Cliente*',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Se não tiver permissão para alterar status de análise E não tiver permissão para visualizar consulta Serasa
        if not (user and (user.has_perm('vendas.change_status_analise') or user.has_perm('vendas.view_consulta_serasa'))):
            self.fields.pop('consulta_serasa', None)
            self.fields.pop('consulta_serasa_analise', None)
            self.fields.pop('restricao', None)

        # 1) Se não tiver permissão, remove todos os campos que terminam em "_analise"
        if not (user and user.has_perm('vendas.view_all_analise_credito')):
            for name in list(self.fields):
                if name.endswith('_analise'):
                    self.fields.pop(name)

        # 2) Inicializa as checkboxes (se elas existirem)
        for analise_field in (
            'documento_identificacao_frente_analise',
            'documento_identificacao_verso_analise',
            'comprovante_residencia_analise',
            'consulta_serasa_analise',
            'restricao',
        ):
            if analise_field in self.fields:
                self.fields[analise_field].initial = False

        # 3) Torna obrigatórios todos os outros campos (mesmo lógica que você já tinha)
        exceptions = {
            'consulta_serasa',
            'consulta_serasa_analise',
            'documento_identificacao_frente_analise',
            'documento_identificacao_verso_analise',
            'comprovante_residencia_analise',
        }
        for name, field in self.fields.items():
            if name not in exceptions:
                field.required = True
        
        if self.instance and self.instance.pk:
            if user and not user.has_perm('vendas.change_status_analise'):
                self.fields['documento_identificacao_frente'].disabled = True
                self.fields['documento_identificacao_verso'].disabled = True
                self.fields['comprovante_residencia'].disabled = True
                self.fields['foto_cliente'].disabled = True
            
            if user and not user.has_perm('vendas.can_edit_finished_sale'):
                if self.instance.cliente.analise_credito and not self.instance.cliente.analise_credito.status == 'EA':
                    self.fields['documento_identificacao_frente'].disabled = True
                    self.fields['documento_identificacao_verso'].disabled = True
                    self.fields['comprovante_residencia'].disabled = True
                    self.fields['consulta_serasa'].disabled = True
                    self.fields['foto_cliente'].disabled = True
                    
                    
class EnderecoForm(forms.ModelForm):
    class Meta:
        model = Endereco
        fields = '__all__'
        exclude = ['loja']
        widgets = {
            'cep': forms.TextInput(attrs={'class': 'form-control'}),
            'bairro': forms.TextInput(attrs={'class': 'form-control'}),
            'cidade': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.TextInput(attrs={'class': 'form-control'}),
            'numero': forms.TextInput(attrs={'class': 'form-control'}),
            'complemento': forms.TextInput(attrs={'class': 'form-control'}),
        }



class TipoPagamentoForm(forms.ModelForm):
    class Meta:
        model = TipoPagamento
        fields = '__all__'
        exclude= ['loja']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'caixa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'parcelas': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'financeira': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'carne': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'nao_contabilizar': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'caixa': 'Esse pagamento será realizado no caixa nas formas de recebimento pelo logista.',
            'parcelas': 'Marque se o pagamento pode ser parcelado.',
            'financeira': 'Marque se o pagamento é feito por financeira.',
            'carne': 'Marque se o pagamento é feito por carnê ou promissória.',
            'nao_contabilizar': 'Marque se o pagamento não deve ser contabilizado.',
        }
        labels = {
            'nome': 'Nome*',
            'caixa': 'Caixa',
            'parcelas': 'Parcelas',
            'financeira': 'Financeira',
            'carne': 'Carnê',
            'nao_contabilizar': 'Não Contabilizar',
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

    
class VendaForm(forms.ModelForm):
    class Meta:
        model = Venda
        fields = '__all__'
        exclude = ['loja','criado_por', 'modificado_por', 'caixa', 'produtos']

        widgets = {
            'cliente': forms.Select(attrs={'class': 'form-control'}),
            'vendedor': forms.Select(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'cliente': 'Cliente*',
            'vendedor': 'Vendedor*',
            'observacao': 'Observação',
        }

    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs) 
        # if loja:
            # self.fields['cliente'].queryset = Cliente.objects.filter(loja=loja)
            # self.fields['vendedor'].queryset = Loja.objects.get(id=loja).usuarios.all()
        # if user:
        #     self.fields['vendedor'].initial = user


class ProdutoSelectWidget(HeavySelect2Widget):
    data_view = 'vendas:produtos_ajax'


class ProdutoVendaForm(forms.ModelForm):
    valor_total = forms.DecimalField(label='Valor Total', disabled=True, required=False, widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly', 'width': '100%'}))
    imei = forms.ModelChoiceField(
        queryset=EstoqueImei.objects.filter(vendido=False),
        label='imei',
        required=False,
        widget=EstoqueImeiSelectWidget(
            max_results=10,
            attrs={
                'class': 'form-control',
                'data-minimum-input-length': '0',
                'data-placeholder': 'Selecione um IMEI',
                'data-allow-clear': 'true',
            }
        )
    )
    produto = forms.ModelChoiceField(
        queryset=Produto.objects.all(),
        label="Produto",
        widget=ProdutoSelectWidget(
            max_results=10,
            attrs={
                'class': 'form-control',
                'data-minimum-input-length': '0',
                'data-placeholder': 'Selecione um produto',
                'data-allow-clear': 'true',
            },
        )
    )

    class Meta:
        model = ProdutoVenda
        fields = '__all__'
        exclude = ['loja', 'venda']
        widgets = {
            'valor_unitario': forms.TextInput(attrs={'class': 'form-control money'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control'}),
            'valor_desconto': forms.TextInput(attrs={'class': 'form-control money'}),
        }
        labels = {
            'valor_unitario': 'Valor*',
            'valor_desconto': 'Desconto*',
            'quantidade': 'Quantidade*', 
            'produto': 'Produto*',
        }
    
    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(
            Exists(
                Estoque.objects.filter(
                    produto=OuterRef('pk'),
                    quantidade_disponivel__gt=0
                )
            )
        ).filter(loja=loja)
        self.fields['imei'].queryset = EstoqueImei.objects.filter(vendido=False, cancelado=False)
        
        
class ProdutoVendaEditForm(forms.ModelForm):
    valor_total = forms.DecimalField(
        label='Valor Total',
        disabled=True,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control money', 'readonly': 'readonly'})
    )
    # quero apenas o produto que está na venda
    produto = forms.ModelChoiceField(
        queryset=None,
        label="Produto",
    )

    class Meta:
        model = ProdutoVenda
        fields = '__all__'
        exclude = ['loja', 'venda']
        widgets = {
            'valor_unitario': forms.TextInput(attrs={'class': 'form-control money'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control'}),
            'valor_desconto': forms.TextInput(attrs={'class': 'form-control money'}),
            'imei': EstoqueImeiSelectWidgetEdit(
                max_results=10,
                attrs={
                    'class': 'form-control',
                    'data-minimum-input-length': '0',
                    'data-placeholder': 'Selecione um IMEI',
                    'data-allow-clear': 'true',
                }
            )
        }
        labels = {
            'valor_unitario': 'Valor*',
            'valor_desconto': 'Desconto*',
            'quantidade': 'Quantidade*', 
            'produto': 'Produto*',
        }
    
    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(loja=loja).filter(id=self.instance.produto.id)



class PagamentoForm(forms.ModelForm):
    valor_parcela = forms.DecimalField(label='Valor Parcela', disabled=True, required=False, widget=forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly'}))
    class Meta:
        model = Pagamento
        fields = '__all__'
        exclude = ['venda', 'loja']
        widgets = {
            'tipo_pagamento': forms.Select(attrs={'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control money'}),
            'parcelas': forms.NumberInput(attrs={'class': 'form-control'}),
            'data_primeira_parcela': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
        labels = {
            'tipo_pagamento': 'Tipo de Pagamento*',
            'valor': 'Valor*',
            'parcelas': 'Parcelas*',
            'data_primeira_parcela': 'Data Primeira Parcela*',
        }

    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        super().__init__(*args, **kwargs)
        if loja:
            self.fields['tipo_pagamento'].queryset = TipoPagamento.objects.filter(loja=loja)
            # ajustar data da primeira parcela para o padrao yyyy-MM-dd
            self.fields['data_primeira_parcela'].widget.format = '%Y-%m-%d'

class LancamentoForm(forms.ModelForm):
    class Meta:
        model = LancamentoCaixa
        fields = '__all__'
        exclude = ['loja', 'caixa']
        widgets = {
            'motivo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_lancamento': forms.Select(attrs={'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control money'}),
        }
        labels = {
            'motivo': 'Motivo*',
            'tipo_lancamento': 'Tipo de Lançamento*',
            'valor': 'Valor*',
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
        
class LancamentoCaixaTotalForm(forms.ModelForm):
    class Meta:
        model = LancamentoCaixaTotal
        fields = '__all__'
        exclude = ['loja', 'caixa']
        widgets = {
            'motivo': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_lancamento': forms.Select(attrs={'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control money'}),
        }
        labels = {
            'motivo': 'Motivo*',
            'tipo_lancamento': 'Tipo de Lançamento*',
            'valor': 'Valor*',
        }

FormaPagamentoFormSet = forms.inlineformset_factory(Venda, Pagamento, form=PagamentoForm, extra=1, can_delete=False)
ProdutoVendaFormSet = forms.inlineformset_factory(Venda, ProdutoVenda, form=ProdutoVendaForm, extra=1, can_delete=False)

FormaPagamentoEditFormSet = forms.inlineformset_factory(Venda, Pagamento, form=PagamentoForm, extra=0, can_delete=True)
ProdutoVendaEditFormSet = forms.inlineformset_factory(Venda, ProdutoVenda, form=ProdutoVendaEditForm, extra=0, can_delete=True)


class UsuarioSelectWidget(ModelSelect2MultipleWidget):
    search_fields = [
        'username__icontains', 
        'first_name__icontains', 
        'last_name__icontains'
    ]
    

class LojaForm(forms.ModelForm):
    usuarios = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=UsuarioSelectWidget(attrs={'class': 'form-control'}),
        required=False
    )

    gerentes = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        widget=UsuarioSelectWidget(attrs={'class': 'form-control'}),
        required=False
    )

    class Meta:
        model = Loja
        fields = '__all__'

        widgets = {
            'telefone': forms.TextInput(attrs={'class': 'form-control tel'}),
            'meta_vendas_diaria': forms.NumberInput(attrs={'class': 'form-control money'}),
            'meta_vendas_mensal': forms.NumberInput(attrs={'class': 'form-control money'}),
            'entrada_caixa_diaria': forms.NumberInput(attrs={'class': 'form-control money'}),
            'porcentagem_desconto': forms.NumberInput(attrs={'class': 'form-control money'}),
        }        

    def __init__(self, *args, **kwargs):
        user_loja_id = kwargs.pop('user_loja', None)
        super().__init__(*args, **kwargs)

        if user_loja_id:
            self.fields['loja'].initial = Loja.objects.get(id=user_loja_id)

        if self.instance and self.instance.porcentagem_desconto_4 is not None:
            self.initial['porcentagem_desconto_4'] = str(self.instance.porcentagem_desconto_4).replace(',', '.')
            
        if self.instance and self.instance.porcentagem_desconto_6 is not None:
            self.initial['porcentagem_desconto_6'] = str(self.instance.porcentagem_desconto_6).replace(',', '.')
            
        if self.instance and self.instance.porcentagem_desconto_8 is not None:
            self.initial['porcentagem_desconto_8'] = str(self.instance.porcentagem_desconto_8).replace(',', '.')


    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if not instance.loja:
            instance.loja = self.fields['loja'].initial
        if commit:
            instance.save()
            self.save_m2m()
        return instance
    


class RelatorioVendasForm(forms.Form):
    data_inicial = forms.DateField(
        label='Data Inicial',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    data_final = forms.DateField(
        label='Data Final',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    produtos = forms.ModelMultipleChoiceField(
        queryset=Produto.objects.all(),
        label='Produtos',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    cliente = forms.ModelMultipleChoiceField(
        queryset=Cliente.objects.all(),
        label='Clientes',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    vendedores = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        label='Vendedores',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    analise_serasa = forms.MultipleChoiceField(
        label='Resultado Serasa',
        required=False,
        choices=[
            ('True', 'Positiva'),
            ('False', 'Negativa'),
        ],
    )
    parcelas = forms.MultipleChoiceField(
        label='Número de Parcelas',
        required=False,
        choices=[],  # serão preenchidas em __init__
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    lojas = forms.ModelMultipleChoiceField(
        queryset=Loja.objects.all(),
        label='Lojas',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        user = kwargs.pop('user', None)
        print(f'Loja no form: {loja}')
        super().__init__(*args, **kwargs)
        if loja:
            self.fields['produtos'].queryset = Produto.objects.all()
            self.fields['cliente'].queryset = Cliente.objects.filter(loja=loja)
            self.fields['vendedores'].queryset = User.objects.filter(loja=loja)
            if user and not user.has_perm('vendas.can_view_all_stores'):
                self.fields['lojas'].queryset = Loja.objects.filter(pk=loja)
            else:
                self.fields['lojas'].queryset = Loja.objects.all()
            self.fields['lojas'].initial = loja
            
        parcelas_qs = (
            AnaliseCreditoCliente.objects
            .order_by('numero_parcelas')
            .values_list('numero_parcelas', flat=True)
            .distinct()
        )
        self.fields['parcelas'].choices = [
            (num, str(num)) for num in parcelas_qs
        ]


class RelatorioSolicitacoesForm(forms.Form):
    data_inicial = forms.DateField(
        label='Data Inicial',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    data_final = forms.DateField(
        label='Data Final',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )

    produtos = forms.ModelMultipleChoiceField(
        label='Produtos',
        queryset=Produto.objects.all(),
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    cliente = forms.ModelMultipleChoiceField(
        label='Clientes',
        queryset=Cliente.objects.all(),
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    vendedores = forms.ModelMultipleChoiceField(
        label='Vendedores',
        queryset=User.objects.all(),
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    lojas = forms.ModelMultipleChoiceField(
        label='Lojas',
        queryset=Loja.objects.all(),
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )

    status_solicitacao = forms.MultipleChoiceField(
        label='Status da Solicitação',
        required=False,
        choices=[],  # serão preenchidas em __init__
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    parcelas = forms.MultipleChoiceField(
        label='Número de Parcelas',
        required=False,
        choices=[],  # serão preenchidas em __init__
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    analise_serasa = forms.MultipleChoiceField(
        label='Resultado Serasa',
        required=False,
        choices=[
            ('True', 'Positiva'),
            ('False', 'Negativa'),
        ],
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    venda_realizada = forms.TypedChoiceField(
        label='Venda Realizada',
        required=False,
        choices=[
            ('', '---------'),
            ('True', 'Sim'),
            ('False', 'Não'),
        ],
        coerce=lambda v: None if v == '' else (v == 'True'),
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        loja = kwargs.pop('loja', None)
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Se houver loja no contexto, limitamos alguns querysets
        if loja:
            self.fields['produtos'].queryset   = Produto.objects.filter(loja=loja)
            self.fields['cliente'].queryset    = Cliente.objects.filter(loja=loja)
            self.fields['vendedores'].queryset = User.objects.filter(loja=loja)
            if user and not user.has_perm('vendas.can_view_all_stores'):
                self.fields['lojas'].queryset = Loja.objects.filter(pk=loja)
            self.fields['lojas'].initial       = [loja]

        # Carrega escolhas de status diretamente do modelo AnaliseCredito
        self.fields['status_solicitacao'].choices = [
            (code, label) for code, label in AnaliseCreditoCliente.STATUS_CHOICES
        ]

        # Carrega escolhas de parcelas a partir dos valores distintos no banco
        parcelas_qs = (
            AnaliseCreditoCliente.objects
            .order_by('numero_parcelas')
            .values_list('numero_parcelas', flat=True)
            .distinct()
        )
        self.fields['parcelas'].choices = [
            (num, str(num)) for num in parcelas_qs
        ]


# vendas/forms.py
from django.core.validators import RegexValidator

class ClienteConsultaForm(forms.Form):
    cpf = forms.CharField(
        label="CPF",
        max_length=14,
        validators=[
            RegexValidator(
                regex=r'^\d{3}\.\d{3}\.\d{3}\-\d{2}$|^\d{11}$',
                message="Informe um CPF válido (somente números ou formatado)."
            )
        ],
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '000.000.000-00'
        })
    )
    date_of_birth = forms.DateField(
        label="Data de Nascimento",
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control'
        })
    )

class ContatoForm(forms.ModelForm):
    data = forms.DateField(
        input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'class': 'form-control', 'type': 'date'}
        )
    )

    class Meta:
        model = Contato
        fields = ['data', 'observacao']
        widgets = {
            'observacao': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3}
            ),
        }