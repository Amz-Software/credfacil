from django import forms
from accounts.models import User
from .models import *
from vendas.models import *
from django_select2.forms import Select2Widget, ModelSelect2Widget, Select2MultipleWidget
from django_select2.forms import ModelSelect2MultipleWidget, HeavySelect2Widget

class PagamentoForm(forms.ModelForm):
    class Meta:
        model = Pagamento
        fields = '__all__'


class ParcelaForm(forms.ModelForm):
    class Meta:
        model = Parcela
        exclude = ['desconto', 'tipo_pagamento', 'valor_pago']
        widgets = {
            'data_vencimento': forms.DateInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'valor': forms.TextInput(attrs={ 'class': 'form-control', 'readonly': 'readonly'}),
            'pago': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'numero_parcela': forms.NumberInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'data_pagamento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'pagamento_efetuado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'disabled': 'disabled'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Verifica se o usuário tem permissão para editar data de vencimento
        can_edit_vencimento = user and user.has_perm('vendas.change_vencimento_parcela')
        
        # Verifica se o usuário tem permissão para editar pagamentos
        can_edit_pagamento = user and user.has_perm('vendas.change_pagamento')
        
        if not can_edit_pagamento:
            # Desabilita todos os campos se não tem permissão de pagamento
            for field in self.fields.values():
                field.disabled = True
                field.widget.attrs['disabled'] = 'disabled'
        else:
            # Se tem permissão de pagamento, verifica permissão específica para vencimento
            if can_edit_vencimento:
                # Remove readonly da data de vencimento se o usuário tem permissão
                self.fields['data_vencimento'].widget.attrs.pop('readonly', None)
                self.fields['data_vencimento'].widget.attrs['type'] = 'date'
            else:
                # Se não tem permissão para editar vencimento, mantém readonly
                self.fields['data_vencimento'].widget.attrs['readonly'] = 'readonly'
                self.fields['data_vencimento'].widget.attrs.pop('type', None)

class GastosAleatoriosForm(forms.ModelForm):
    class Meta:
        model = GastosAleatorios
        fields = ['descricao', 'observacao', 'valor']
        widgets = {
            'descricao': forms.TextInput(attrs={'class': 'form-control', 'style': 'background-color: #d4edda;'}),
            'observacao': forms.Textarea(attrs={'rows': 1, 'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control money', 'style': 'background-color: #d4edda;'}),
        }
class GastoFixoForm(forms.ModelForm):
    class Meta:
        model = GastoFixo
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'nome': 'Nome do Gasto Fixo',
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

class CaixaMensalGastoFixoForm(forms.ModelForm):
    class Meta:
        model = CaixaMensalGastoFixo
        fields = ['gasto_fixo', 'observacao', 'valor']
        widgets = {
            'gasto_fixo': forms.Select(attrs={'class': 'form-select'}),
            'observacao': forms.Textarea(attrs={'rows': 1, 'class': 'form-control'}),
            'valor': forms.TextInput(attrs={'class': 'form-control money', 'style': 'background-color: #d4edda;'}),
        }

    def __init__(self, *args, **kwargs):
        super(CaixaMensalGastoFixoForm, self).__init__(*args, **kwargs)
        self.fields['gasto_fixo'].queryset = GastoFixo.objects.filter(loja=self.instance.caixa_mensal.loja)


class CaixaMensalFuncionarioForm(forms.ModelForm):
    nome = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))

    class Meta:
        model = CaixaMensalFuncionario
        fields = ['comissao', 'salario']
        widgets = {
            'comissao': forms.TextInput(attrs={'class': 'form-control money'}),
            'salario': forms.TextInput(attrs={'class': 'form-control money', 'style': 'background-color: #d4edda;'}),
        }
        labels = {
            'comissao': 'Comissão',
            'salario': 'Salário',
        }
    
    def __init__(self, *args, **kwargs):
        super(CaixaMensalFuncionarioForm, self).__init__(*args, **kwargs)
        # Preencher o campo nome com o nome do funcionário 
        self.fields['nome'].initial = f'{self.instance.funcionario.first_name} {self.instance.funcionario.last_name}'
        self.fields['nome'].widget.attrs['readonly'] = 'readonly'

# Definições dos FormSets com Prefixo
CaixaMensalGastoFixoFormSet = forms.modelformset_factory(
    CaixaMensalGastoFixo,
    form=CaixaMensalGastoFixoForm,
    extra=0
)

CaixaMensalFuncionarioFormSet = forms.modelformset_factory(
    CaixaMensalFuncionario,
    form=CaixaMensalFuncionarioForm,
    extra=0,
    can_delete=True
)

GastosAleatoriosFormSet = forms.inlineformset_factory(
    CaixaMensal,
    GastosAleatorios,
    form=GastosAleatoriosForm,
    extra=0,
    can_delete=True
)

ParcelaInlineFormSet = forms.inlineformset_factory(
    Pagamento,
    Parcela,
    form=ParcelaForm,
    extra=0,
    can_delete=True
)

class RelatorioContasAReceberForm(forms.Form):
    data_inicial = forms.DateField(
        label='Data Inicial',
        required=True,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    data_final = forms.DateField(
        label='Data Final',
        required=True,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    status = forms.ChoiceField(
        choices=[
            ('pendente', 'A Vencer'),
            ('pago', 'Pago'),
            ('atrasado', 'Atrasado'),
            ('desativado', 'Desativados'),
            ('bloqueado', 'Bloqueados'),
            ('sem_contato', 'Sem contato'),
            ('mais_prazo', 'Mais prazo'),
            ('quitado', 'Quitado'),
            ('lembrete', 'Lembrete'),
            ('flag_atrasado', 'Cobrança'),
            ('sem_conexao', 'Sem conexão'),
            ('roubo', 'Roubo'),
            ('devolucao', 'Devolução'),
            ('todos', 'Todos')
        ],
        label='Status',
        required=True,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    lojas = forms.ModelMultipleChoiceField(
        queryset=Loja.objects.all(),
        label='Lojas',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    status_pagamento = forms.ModelMultipleChoiceField(
        queryset=StatusPagamento.objects.all(),
        label='Status Pagamento',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )

class RelatorioSaidaForm(forms.Form):
    data_inicial = forms.DateField(
        label='Data Inicial',
        required=True,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    data_final = forms.DateField(
        label='Data Final',
        required=True,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    lojas = forms.ModelMultipleChoiceField(
        queryset=Loja.objects.all(),
        label='Lojas',
        required=True,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )


class RepasseForm(forms.ModelForm):
    class Meta:
        model = Repasse
        fields = ['loja', 'valor', 'data','status', 'observacao']
        widgets = {
            'loja': forms.HiddenInput(),
            'data': forms.DateInput(
            attrs={
                'class': 'form-control',
                'type': 'date',
                'placeholder': 'Selecione a data (01 ou 16)'
            },
            format='%Y-%m-%d'
            ),
            'valor': forms.TextInput(
            attrs={
                'class': 'form-control money',
                'placeholder': 'Digite o valor'
            }
            ),
            'status': forms.Select(
            attrs={
                'class': 'form-select',
                'placeholder': 'Selecione o status'
            }
            ),
            'observacao': forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Adicione uma observação'
            }
            ),
        }
        labels = {
            'valor': 'Valor do Repasse',
            'data': 'Data do Repasse (dia 01 ou 16)',
            'status': 'Status',
            'observacao': 'Observação',
        }
        help_texts = {
            'data': 'Use dia 01 para o período 16–último do mês anterior e dia 16 para o período 01–15 do mês atual.'
        }


class PagamentoStatusForm(forms.ModelForm):
    class StatusPagamentoSelectWidget(ModelSelect2MultipleWidget):
        search_fields = [
            'nome__icontains',
            'slug__icontains',
        ]

    statuses = forms.ModelMultipleChoiceField(
        queryset=StatusPagamento.objects.all(),
        widget=StatusPagamentoSelectWidget(attrs={'class': 'form-control', 'data-minimum-input-length': 0}),
        required=False,
        label='Status do Pagamento'
    )

    class Meta:
        model = Pagamento
        fields = ['statuses']


class RelatorioContasAReceberAvancadoForm(forms.Form):
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
    lojas = forms.ModelMultipleChoiceField(
        queryset=Loja.objects.all(),
        label='Lojas',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    status_pagamento = forms.ModelMultipleChoiceField(
        queryset=StatusPagamento.objects.all(),
        label='Status Pagamento',
        required=False,
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )
    situacoes = forms.MultipleChoiceField(
        label='Situações',
        required=False,
        choices=[
            ('lembrete','Lembrete'),
            ('bo','BO'),
            ('flag_atrasado','Cobrança'),
            ('sem_conexao','Sem conexão'),
            ('roubo','Roubo'),
            ('bloqueado','Bloquear Aparelho'),
            ('desativado','Desativar Cliente'),
            ('devolucao','Devolução'),
            ('sem_contato','Sem contato'),
            ('mais_prazo','Mais prazo'),
        ],
        widget=Select2MultipleWidget(attrs={'class': 'form-control'})
    )