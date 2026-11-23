"""Serializers de entrada da caixa de entrada do CRM (query e corpo).

Validam só o formato (tipos, tamanhos, escolhas): erro vira 400 com `campos`.
A regra de negócio (trava de resposta, janela, posse, antispam) fica nos serviços do CRM
e volta como 409 `conflito`.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from crm.models import LIMITE_TEXTO, Conversa
from crm.services import midias, organizacao
from crm.web.filtros import FILA_PADRAO, FILAS, ORDENS

from .base import CrmSerializer

LIMITE_BUSCA = 100
LIMITE_EMOJI = 16
LIMITE_NOME = 150
LIMITE_TELEFONE = 30
LIMITE_CHAVE_ABERTURA = 40
MAX_ETIQUETAS = 50
MENSAGENS_POR_PAGINA = 50
MAX_MENSAGENS_POR_PAGINA = 100
ORDEM_PADRAO = 'recentes'


def _usuario(pk: int | None):
    if pk is None:
        return None
    usuario = get_user_model().objects.filter(pk=pk).first()
    if usuario is None:
        raise serializers.ValidationError('Usuário não encontrado.')
    return usuario


# --- leitura --------------------------------------------------------------------------------

class FiltrosConversasSerializer(CrmSerializer):
    fila = serializers.ChoiceField(choices=[valor for valor, _ in FILAS], default=FILA_PADRAO)
    situacao = serializers.ChoiceField(choices=Conversa.Situacao.values, required=False, allow_blank=True)
    etiqueta = serializers.IntegerField(required=False, min_value=1)
    nao_lidas = serializers.BooleanField(required=False, default=False)
    busca = serializers.CharField(required=False, allow_blank=True, max_length=LIMITE_BUSCA)
    ordenar = serializers.ChoiceField(choices=[valor for valor, _ in ORDENS], default=ORDEM_PADRAO,
                                      help_text='recentes (última mensagem) ou espera (abertas primeiro, maior espera).')
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, help_text='Máximo 100 (padrão 25).')


class CursorMensagensSerializer(CrmSerializer):
    antes = serializers.IntegerField(required=False, min_value=1)
    limite = serializers.IntegerField(required=False, min_value=1, max_value=MAX_MENSAGENS_POR_PAGINA,
                                      default=MENSAGENS_POR_PAGINA)


class BuscaClientesQuerySerializer(CrmSerializer):
    busca = serializers.CharField(required=False, allow_blank=True, max_length=LIMITE_BUSCA, default='')
    conversa = serializers.IntegerField(required=False, min_value=1)


class ClienteQuerySerializer(CrmSerializer):
    cliente = serializers.IntegerField(min_value=1)


# --- posse, situação e organização ----------------------------------------------------------

class PuxarSerializer(CrmSerializer):
    de = serializers.IntegerField(required=False, allow_null=True, min_value=1,
                                  help_text='Dono que a tela mostrava; se mudou, a ação é recusada (409).')


class AtribuirSerializer(CrmSerializer):
    usuario = serializers.IntegerField(min_value=1)

    def validate_usuario(self, valor: int):
        return _usuario(valor)


class SituacaoSerializer(CrmSerializer):
    situacao = serializers.ChoiceField(choices=Conversa.Situacao.values)
    devolver_automatico = serializers.BooleanField(required=False, default=False)


class EtiquetasSerializer(CrmSerializer):
    etiquetas = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True,
                                      max_length=MAX_ETIQUETAS, help_text='Conjunto completo (substitui o atual).')


class ApelidoSerializer(CrmSerializer):
    apelido = serializers.CharField(required=False, allow_blank=True, default='',
                                    max_length=organizacao.LIMITE_APELIDO)


class ClienteSerializer(CrmSerializer):
    cliente = serializers.IntegerField(min_value=1)


class AberturaEnvioSerializer(CrmSerializer):
    modelo = serializers.CharField(max_length=LIMITE_CHAVE_ABERTURA, help_text='`chave` da mensagem de abertura.')
    nome = serializers.CharField(required=False, allow_blank=True, default='', max_length=LIMITE_NOME)


class IniciarSerializer(AberturaEnvioSerializer):
    telefone = serializers.CharField(max_length=LIMITE_TELEFONE, help_text='Com DDD; o 55 é acrescentado.')


# --- envio ----------------------------------------------------------------------------------

class EnviarSerializer(CrmSerializer):
    texto = serializers.CharField(required=False, allow_blank=True, default='', max_length=LIMITE_TEXTO,
                                  help_text='Texto, ou legenda do arquivo (até 1024).')
    arquivo = serializers.FileField(required=False, help_text='Até 25 MB; o tipo vem do conteúdo.')
    responde_a = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    voz = serializers.BooleanField(required=False, default=False, help_text='Áudio gravado (mensagem de voz).')

    def validate_arquivo(self, arquivo):
        if arquivo is not None and arquivo.size > midias.LIMITE_ENVIO:
            raise serializers.ValidationError('O arquivo passa de 25 MB.')
        return arquivo

    def validate(self, dados: dict) -> dict:
        if dados.get('arquivo') is None and not dados.get('texto', '').strip():
            raise serializers.ValidationError({'texto': ['Escreva a mensagem antes de enviar.']})
        return dados


class ReagirSerializer(CrmSerializer):
    emoji = serializers.CharField(required=False, allow_blank=True, default='', max_length=LIMITE_EMOJI,
                                  help_text='Vazio remove a reação.')


# --- notas, lembrete e programadas ----------------------------------------------------------

class NotaEntradaSerializer(CrmSerializer):
    texto = serializers.CharField(max_length=organizacao.LIMITE_NOTA)


class LembreteEntradaSerializer(CrmSerializer):
    lembrete_em = serializers.DateTimeField(help_text='ISO 8601; sem fuso = horário do sistema.')
    texto = serializers.CharField(required=False, allow_blank=True, default='',
                                  max_length=organizacao.LIMITE_LEMBRETE)
    para = serializers.IntegerField(required=False, allow_null=True, min_value=1,
                                    help_text='Padrão: quem está criando.')

    def validate_para(self, valor: int | None):
        return _usuario(valor)


class ProgramarSerializer(CrmSerializer):
    texto = serializers.CharField(max_length=LIMITE_TEXTO)
    enviar_em = serializers.DateTimeField(help_text='Entre 5 minutos e 30 dias à frente.')
