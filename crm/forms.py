"""Formulários das telas de configuração do CRM no backoffice."""
from django import forms

from crm.models import ConfiguracaoCRM, Etiqueta, RespostaRapida

MAX_HORAS_RETORNO = 720


class _BootstrapMixin:
    """Aplica as classes do Bootstrap/Sneat aos widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.fields.values():
            widget = campo.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class ConfiguracaoForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ConfiguracaoCRM
        fields = ['nome_empresa', 'boas_vindas_ativa', 'mensagem_boas_vindas', 'retorno_automatico_horas',
                  'autoatendimento_ativo', 'url_publica']
        labels = {
            'nome_empresa': 'Nome da empresa nas mensagens',
            'boas_vindas_ativa': 'Enviar boas-vindas quando o cliente chamar',
            'mensagem_boas_vindas': 'Mensagem de boas-vindas',
            'retorno_automatico_horas': 'Devolver ao automático após (horas sem resposta da equipe)',
            'autoatendimento_ativo': 'Autoatendimento de parcelas (CPF + data de nascimento)',
            'url_publica': 'Endereço público do sistema',
        }
        help_texts = {'retorno_automatico_horas': '0 desliga a devolução automática.'}
        widgets = {'mensagem_boas_vindas': forms.Textarea(attrs={'rows': 3})}

    def clean_retorno_automatico_horas(self) -> int:
        horas = self.cleaned_data['retorno_automatico_horas']
        if horas > MAX_HORAS_RETORNO:
            raise forms.ValidationError(f'Use no máximo {MAX_HORAS_RETORNO} horas.')
        return horas

    def clean_url_publica(self) -> str:
        valor = (self.cleaned_data.get('url_publica') or '').strip().rstrip('/')
        if valor and not valor.startswith('https://'):
            raise forms.ValidationError('Use um endereço que comece com https://')
        return valor


class EtiquetaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Etiqueta
        fields = ['nome', 'cor', 'ordem', 'ativo']

    def clean_nome(self) -> str:
        nome = self.cleaned_data['nome'].strip()
        repetida = Etiqueta.objects.filter(nome__iexact=nome)
        if self.instance.pk:
            repetida = repetida.exclude(pk=self.instance.pk)
        if repetida.exists():
            raise forms.ValidationError('Já existe uma etiqueta com esse nome.')
        return nome


class RespostaRapidaForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = RespostaRapida
        fields = ['atalho', 'titulo', 'texto', 'ordem', 'ativo']
        help_texts = {
            'atalho': 'Sem espaços. Ex.: boleto',
            'texto': 'Marcadores: {primeiro_nome}, {nome_cliente}, {empresa}, {atendente}.',
        }
        widgets = {'texto': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, data=None, *args, **kwargs):
        if data is not None and isinstance(data.get('atalho'), str):
            data = data.copy()
            data['atalho'] = data['atalho'].strip().lstrip('/').lower()
        super().__init__(data, *args, **kwargs)
