"""Serializers da configuração do CRM (`crm.gerenciar_crm`).

Etiquetas, respostas rápidas e a configuração geral são validadas pelos forms das telas
(`crm/forms.py`, via `servicos.validar_form`); aqui ficam a saída e a entrada das aberturas
e do simulador.
"""
from rest_framework import serializers

from crm.forms import ConfiguracaoForm
from crm.models import ConfiguracaoCRM, Etiqueta, RespostaRapida, VersaoAbertura
from crm.services import aberturas

from .base import CrmModelSerializer, CrmSerializer
from .saida import MensagemSerializer, UsuarioMiniSerializer

SIMULACOES = ('APROVADO', 'REJEITADO')
LIMITE_TELEFONE_SIMULADOR = 20
LIMITE_NOME = 150
LIMITE_TEXTO_SIMULADOR = 4096


# --- geral ----------------------------------------------------------------------------------

class ConfiguracaoCRMSerializer(CrmModelSerializer):
    class Meta:
        model = ConfiguracaoCRM
        fields = [*ConfiguracaoForm._meta.fields, 'atualizado_em']
        read_only_fields = fields


class ItemIntegracaoSerializer(CrmSerializer):
    variavel = serializers.CharField()
    descricao = serializers.CharField()
    ok = serializers.BooleanField(help_text='Só diz se está definida; o valor nunca sai do servidor.')


class IntegracaoSerializer(CrmSerializer):
    modo_real = serializers.BooleanField()
    itens = ItemIntegracaoSerializer(many=True)
    transcricao = serializers.BooleanField(help_text='OPENAI_API_KEY definida (transcrição de áudios).')
    api_version = serializers.CharField()
    webhook_url = serializers.CharField()
    privacidade_url = serializers.CharField()


class ConfiguracaoGeralSerializer(CrmSerializer):
    configuracao = ConfiguracaoCRMSerializer()
    integracao = IntegracaoSerializer()
    simulado = serializers.BooleanField()


def _entrada_opcional(campos) -> dict:
    return {campo: {'required': False} for campo in campos}


class ConfiguracaoEntradaSerializer(CrmModelSerializer):
    """Só documenta a entrada (OpenAPI); quem valida é o `ConfiguracaoForm` das telas."""

    class Meta:
        model = ConfiguracaoCRM
        fields = list(ConfiguracaoForm._meta.fields)
        extra_kwargs = _entrada_opcional(fields)


class EtiquetaEntradaSerializer(CrmModelSerializer):
    """Só documenta a entrada; quem valida é o `EtiquetaForm` (nome único, sem diferenciar maiúsculas)."""

    class Meta:
        model = Etiqueta
        fields = ['nome', 'cor', 'ordem', 'ativo']


class RespostaRapidaEntradaSerializer(CrmModelSerializer):
    """Só documenta a entrada; quem valida é o `RespostaRapidaForm` (atalho sem barra e minúsculo)."""

    class Meta:
        model = RespostaRapida
        fields = ['atalho', 'titulo', 'texto', 'ordem', 'ativo']


# --- cadastros ------------------------------------------------------------------------------

class EtiquetaSerializer(CrmModelSerializer):
    cor_display = serializers.CharField(source='get_cor_display', read_only=True)

    class Meta:
        model = Etiqueta
        fields = ['id', 'nome', 'cor', 'cor_display', 'ordem', 'ativo']
        read_only_fields = fields


class RespostaRapidaSerializer(CrmModelSerializer):
    criado_por = serializers.SerializerMethodField()

    class Meta:
        model = RespostaRapida
        fields = ['id', 'atalho', 'titulo', 'texto', 'ordem', 'ativo', 'criado_por']
        read_only_fields = fields

    def get_criado_por(self, resposta) -> dict | None:
        usuario = resposta.criado_por
        if usuario is None:
            return None
        return UsuarioMiniSerializer({'id': usuario.pk, 'nome': usuario.get_full_name() or usuario.username}).data


# --- aberturas ------------------------------------------------------------------------------

class VersaoAberturaSerializer(CrmSerializer):
    versao = serializers.IntegerField()
    corpo = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.SerializerMethodField()
    motivo = serializers.CharField(allow_blank=True, help_text='Motivo da rejeição na Meta.')
    erro = serializers.CharField(allow_blank=True)
    nome_meta = serializers.CharField()
    criado_em = serializers.DateTimeField()

    def get_status_display(self, versao: dict) -> str:
        return VersaoAbertura.Status(versao['status']).label


class AberturaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    chave = serializers.CharField()
    titulo = serializers.CharField()
    ordem = serializers.IntegerField()
    ativo = serializers.BooleanField()
    vigente = VersaoAberturaSerializer(allow_null=True, help_text='Versão aprovada que sai hoje.')
    em_analise = VersaoAberturaSerializer(allow_null=True)
    ultima = VersaoAberturaSerializer(allow_null=True)


def _validar_corpo(corpo: str) -> str:
    erros = aberturas.validar_corpo(corpo)
    if erros:
        raise serializers.ValidationError(erros)
    return corpo.strip()


class AberturaCriarSerializer(CrmSerializer):
    titulo = serializers.CharField(min_length=3, max_length=60)
    corpo = serializers.CharField(max_length=aberturas.LIMITE_CORPO, help_text='Aceita o marcador {nome} uma vez.')

    def validate_corpo(self, corpo: str) -> str:
        return _validar_corpo(corpo)


class AberturaEditarSerializer(CrmSerializer):
    titulo = serializers.CharField(required=False, min_length=3, max_length=60)
    ordem = serializers.IntegerField(required=False, min_value=0, max_value=1000)
    ativo = serializers.BooleanField(required=False)
    corpo = serializers.CharField(required=False, allow_blank=True, max_length=aberturas.LIMITE_CORPO,
                                  help_text='Texto diferente do atual vira versão nova enviada à Meta.')

    def validate_corpo(self, corpo: str) -> str:
        return _validar_corpo(corpo) if corpo.strip() else ''


class SimularDecisaoSerializer(CrmSerializer):
    status = serializers.ChoiceField(choices=SIMULACOES)


# --- simulador ------------------------------------------------------------------------------

class SimuladorReceberSerializer(CrmSerializer):
    telefone = serializers.CharField(max_length=LIMITE_TELEFONE_SIMULADOR)
    nome = serializers.CharField(required=False, allow_blank=True, default='', max_length=LIMITE_NOME)
    texto = serializers.CharField(max_length=LIMITE_TEXTO_SIMULADOR)


class SimuladorLerSerializer(CrmSerializer):
    conversa = serializers.IntegerField(min_value=1)


class SimuladorRecebidaSerializer(CrmSerializer):
    conversa_id = serializers.IntegerField(allow_null=True)
    mensagem = MensagemSerializer(allow_null=True, help_text='Nula se a mensagem foi descartada (telefone curto).')


class SimuladorLeituraSerializer(CrmSerializer):
    alteradas = serializers.IntegerField()


class ConversaSimuladorSerializer(CrmSerializer):
    id = serializers.IntegerField(source='pk')
    nome_exibicao = serializers.CharField()
    telefone = serializers.CharField()


class SimuladorSerializer(CrmSerializer):
    disponivel = serializers.BooleanField(help_text='Só sem as credenciais da Meta.')
    conversas = ConversaSimuladorSerializer(many=True)
