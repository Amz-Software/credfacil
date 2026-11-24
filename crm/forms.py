"""Formulários das telas de configuração do CRM no backoffice."""
from decimal import Decimal

from django import forms

from crm.models import ConfiguracaoCRM, Etiqueta, ModeloAbertura, RespostaRapida

MAX_HORAS_RETORNO = 720
MAX_PERCENTUAL_DIA = Decimal('5')
MAX_INTERVALO_COBRANCA = 30
MAX_INSISTENCIAS = 20
TAMANHO_CNPJ = 14
NOME_ASSISTENTE_PADRAO = 'Ana'


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
                  'autoatendimento_ativo', 'assistente_ativo', 'assistente_nome', 'assistente_conhecimento',
                  'hora_abertura', 'hora_fechamento', 'hora_fechamento_sabado', 'mensagem_fora_horario',
                  'antecipacao_percentual_dia', 'url_publica', 'razao_social', 'cnpj', 'email_privacidade']
        labels = {
            'nome_empresa': 'Nome da empresa nas mensagens',
            'boas_vindas_ativa': 'Enviar boas-vindas quando o cliente chamar',
            'mensagem_boas_vindas': 'Mensagem de boas-vindas',
            'retorno_automatico_horas': 'Devolver ao automático após (horas sem resposta da equipe)',
            'autoatendimento_ativo': 'Autoatendimento de parcelas (CPF + data de nascimento)',
            'assistente_ativo': 'Assistente de IA (conversa em linguagem natural)',
            'assistente_nome': 'Nome do assistente',
            'assistente_conhecimento': 'O que o assistente sabe (IPX Consulta, regras, horários)',
            'hora_abertura': 'Equipe começa a atender às',
            'hora_fechamento': 'Equipe para de atender às (segunda a sexta)',
            'hora_fechamento_sabado': 'Equipe para de atender às (sábado)',
            'mensagem_fora_horario': 'Mensagem de fora do horário',
            'antecipacao_percentual_dia': 'Desconto de antecipação (% ao dia)',
            'url_publica': 'Endereço público do sistema',
            'razao_social': 'Razão social',
            'cnpj': 'CNPJ',
            'email_privacidade': 'E-mail do responsável pelos dados (LGPD)',
        }
        help_texts = {'retorno_automatico_horas': '0 desliga a devolução automática.'}
        widgets = {'mensagem_boas_vindas': forms.Textarea(attrs={'rows': 3}),
                   'assistente_conhecimento': forms.Textarea(attrs={'rows': 10}),
                   'mensagem_fora_horario': forms.Textarea(attrs={'rows': 3}),
                   'hora_abertura': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
                   'hora_fechamento': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
                   'hora_fechamento_sabado': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')}

    # Em branco = mantém o que já estava (o formulário antigo da API não manda estes campos).
    CAMPOS_MANTIDOS = ('hora_abertura', 'hora_fechamento', 'mensagem_fora_horario')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['assistente_nome'].required = False
        for campo in self.CAMPOS_MANTIDOS:
            self.fields[campo].required = False

    def _mantido(self, campo: str):
        valor = self.cleaned_data.get(campo)
        if valor in (None, ''):
            return getattr(self.instance, campo) or ConfiguracaoCRM._meta.get_field(campo).get_default()
        return valor

    def clean_hora_abertura(self):
        return self._mantido('hora_abertura')

    def clean_hora_fechamento(self):
        return self._mantido('hora_fechamento')

    def clean_mensagem_fora_horario(self) -> str:
        return (self._mantido('mensagem_fora_horario') or '').strip()

    def clean_hora_fechamento_sabado(self):
        # Vazio na tela = não atende no sábado; ausente no envio (cliente antigo da API) = mantém.
        if self.add_prefix('hora_fechamento_sabado') not in self.data:
            return self.instance.hora_fechamento_sabado
        return self.cleaned_data.get('hora_fechamento_sabado')

    def clean_assistente_nome(self) -> str:
        return (self.cleaned_data.get('assistente_nome') or '').strip() or NOME_ASSISTENTE_PADRAO

    def clean_antecipacao_percentual_dia(self):
        valor = self.cleaned_data.get('antecipacao_percentual_dia')
        if valor is not None and not 0 < valor <= MAX_PERCENTUAL_DIA:
            raise forms.ValidationError(f'Use um valor maior que 0 e até {MAX_PERCENTUAL_DIA}% ao dia.')
        return valor

    def clean(self):
        dados = super().clean()
        abertura = dados.get('hora_abertura')
        for campo in ('hora_fechamento', 'hora_fechamento_sabado'):
            fim = dados.get(campo)
            if abertura and fim and fim <= abertura:
                self.add_error(campo, 'O fim do atendimento precisa ser depois do início.')
        return dados

    def clean_retorno_automatico_horas(self) -> int:
        horas = self.cleaned_data['retorno_automatico_horas']
        if horas > MAX_HORAS_RETORNO:
            raise forms.ValidationError(f'Use no máximo {MAX_HORAS_RETORNO} horas.')
        return horas

    def clean_cnpj(self) -> str:
        digitos = ''.join(c for c in self.cleaned_data.get('cnpj') or '' if c.isdigit())
        if not digitos:
            return ''
        if len(digitos) != TAMANHO_CNPJ:
            raise forms.ValidationError('O CNPJ tem 14 dígitos.')
        return f'{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}'

    def clean_url_publica(self) -> str:
        valor = (self.cleaned_data.get('url_publica') or '').strip().rstrip('/')
        if valor and not valor.startswith('https://'):
            raise forms.ValidationError('Use um endereço que comece com https://')
        return valor


class CobrancaForm(_BootstrapMixin, forms.ModelForm):
    """Régua de avisos automáticos: liga/desliga, horário, repetição e o template de cada etapa."""

    CAMPOS_MODELO = ('modelo_aviso_antes', 'modelo_aviso_dia', 'modelo_aviso_apos', 'modelo_aviso_insistencia',
                     'modelo_aviso_quitacao')

    class Meta:
        model = ConfiguracaoCRM
        fields = ['cobranca_ativa', 'cobranca_hora_envio', 'cobranca_intervalo_dias', 'cobranca_max_insistencias',
                  'modelo_aviso_antes', 'modelo_aviso_dia', 'modelo_aviso_apos', 'modelo_aviso_insistencia',
                  'modelo_aviso_quitacao']
        labels = {
            'cobranca_ativa': 'Enviar avisos automáticos de cobrança',
            'cobranca_hora_envio': 'Enviar a partir das',
            'cobranca_intervalo_dias': 'Sem retorno, repetir a cada (dias)',
            'cobranca_max_insistencias': 'Máximo de repetições',
            'modelo_aviso_antes': '3 dias antes do vencimento',
            'modelo_aviso_dia': 'No dia do vencimento',
            'modelo_aviso_apos': '2 dias depois do vencimento (pede o comprovante)',
            'modelo_aviso_insistencia': 'Repetição para quem não respondeu',
            'modelo_aviso_quitacao': 'Quitação (recompra e retirada do app)',
        }
        widgets = {'cobranca_hora_envio': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in self.CAMPOS_MODELO:
            self.fields[campo].queryset = ModeloAbertura.objects.filter(ativo=True)
            self.fields[campo].empty_label = '— não enviar —'
            self.fields[campo].help_text = 'Mensagem de abertura aprovada pela Meta. Use {nome}, {valor} e {vencimento}.'

    def clean_cobranca_intervalo_dias(self) -> int:
        dias = self.cleaned_data['cobranca_intervalo_dias']
        if not 1 <= dias <= MAX_INTERVALO_COBRANCA:
            raise forms.ValidationError(f'Use de 1 a {MAX_INTERVALO_COBRANCA} dias.')
        return dias

    def clean_cobranca_max_insistencias(self) -> int:
        vezes = self.cleaned_data['cobranca_max_insistencias']
        if vezes > MAX_INSISTENCIAS:
            raise forms.ValidationError(f'Use no máximo {MAX_INSISTENCIAS}.')
        return vezes


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
