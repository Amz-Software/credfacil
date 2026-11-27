"""Serializers da Central de cobrança: saúde do número, configuração, agenda e histórico.

Entrada valida só o formato (400 `validacao`); regra de negócio volta como 409 `conflito`.
Os de saída documentam o OpenAPI (componentes `Crm...`) e filtram a resposta montada em
`apresentacao_cobranca`.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from crm.forms import CobrancaForm
from crm.models import ConfiguracaoCRM, TentativaContato
from crm.services.central_cobranca import agenda, historico

from .base import CrmModelSerializer, CrmSerializer

DIAS_HISTORICO_PADRAO = 30
MAX_DIAS_HISTORICO = 366


class _Paginacao(CrmSerializer):
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, help_text='Máximo 100 (padrão 25).')


class MotivoContagemSerializer(CrmSerializer):
    motivo = serializers.CharField()
    rotulo = serializers.CharField()
    quantidade = serializers.IntegerField()


class ClienteMiniCobrancaSerializer(CrmSerializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class ParcelaMiniSerializer(CrmSerializer):
    id = serializers.IntegerField()
    numero = serializers.IntegerField()
    valor = serializers.CharField(help_text='Valor em aberto da parcela ("150.00").')
    vencimento = serializers.DateField()


# --- saúde ---------------------------------------------------------------------------------------

class SaudeQuerySerializer(CrmSerializer):
    atualizar = serializers.BooleanField(required=False, default=False,
                                         help_text='true = lê a Meta agora (sem esperar o cache de 10 min).')


class NumeroMetaSerializer(CrmSerializer):
    limite_tier = serializers.CharField(help_text='TIER_250, TIER_2K, TIER_10K, TIER_100K, TIER_UNLIMITED ou "".')
    limite_meta = serializers.IntegerField(allow_null=True)
    qualidade = serializers.CharField(help_text='GREEN, YELLOW, RED ou "" (desconhecida).')
    qualidade_display = serializers.CharField()
    fonte = serializers.ChoiceField(choices=['meta', 'ultima_leitura', 'padrao'])
    lido_em = serializers.DateTimeField(allow_null=True)
    leitura_falhou = serializers.BooleanField(help_text='A última tentativa de ler a Meta deu erro.')
    pausa = serializers.CharField(help_text='"", pausada_por_qualidade ou sem_leitura_recente.')
    pausa_display = serializers.CharField()


class TetoSerializer(CrmSerializer):
    automatico = serializers.IntegerField()
    configurado = serializers.IntegerField(allow_null=True)
    efetivo = serializers.IntegerField()
    enviados_24h = serializers.IntegerField(help_text='Templates da empresa nas últimas 24 h (janela da Meta).')
    restante_agora = serializers.IntegerField()
    reserva_regua_hoje = serializers.IntegerField(help_text='Avisos que a régua ainda vai mandar hoje.')
    vagas_disparos = serializers.IntegerField(help_text='restante_agora − reserva_regua_hoje.')


class JanelaSerializer(CrmSerializer):
    inicio = serializers.DateTimeField()
    fim = serializers.DateTimeField()


class ReguaSerializer(CrmSerializer):
    status = serializers.ChoiceField(choices=['ativa', 'pausada', 'pausada_por_qualidade', 'sem_leitura_recente',
                                              'antes_da_ativacao'])
    status_display = serializers.CharField()
    ativa = serializers.BooleanField()
    ativada_em = serializers.DateTimeField(allow_null=True)
    hora_envio = serializers.CharField()
    fim_envio = serializers.CharField()
    proxima_janela = JanelaSerializer(allow_null=True)
    enviando_agora = serializers.BooleanField()


class DisparosSaudeSerializer(CrmSerializer):
    em_andamento = serializers.IntegerField()
    situacao_envio = serializers.CharField()
    situacao_envio_display = serializers.CharField()


class SaudeSerializer(CrmSerializer):
    numero = NumeroMetaSerializer()
    teto = TetoSerializer()
    regua = ReguaSerializer()
    disparos = DisparosSaudeSerializer()
    custo_por_mensagem = serializers.CharField()
    simulado = serializers.BooleanField()


# --- configuração --------------------------------------------------------------------------------

class CobrancaEntradaSerializer(CrmModelSerializer):
    """Só documenta a entrada (OpenAPI); quem valida é o `CobrancaForm` das telas."""

    class Meta:
        model = ConfiguracaoCRM
        fields = list(CobrancaForm._meta.fields)
        extra_kwargs = {campo: {'required': False} for campo in CobrancaForm._meta.fields}


class CobrancaValoresSerializer(CrmSerializer):
    cobranca_ativa = serializers.BooleanField()
    cobranca_ativada_em = serializers.DateTimeField(allow_null=True)
    cobranca_hora_envio = serializers.CharField()
    cobranca_pular_bom_pagador = serializers.BooleanField()
    cobranca_intervalo_dias = serializers.IntegerField()
    cobranca_max_insistencias = serializers.IntegerField()
    cobranca_teto_diario = serializers.IntegerField(allow_null=True)
    modelo_aviso_antes = serializers.IntegerField(allow_null=True)
    modelo_aviso_dia = serializers.IntegerField(allow_null=True)
    modelo_aviso_apos = serializers.IntegerField(allow_null=True)
    modelo_aviso_insistencia = serializers.IntegerField(allow_null=True)
    modelo_aviso_quitacao = serializers.IntegerField(allow_null=True)
    modelo_compra_confirmada = serializers.IntegerField(allow_null=True)


class ModeloMiniSerializer(CrmSerializer):
    id = serializers.IntegerField()
    titulo = serializers.CharField()


class EtapaConfigSerializer(CrmSerializer):
    campo = serializers.CharField()
    rotulo = serializers.CharField()
    modelo = ModeloMiniSerializer(allow_null=True)
    pronta = serializers.BooleanField()


class ModeloOpcaoSerializer(ModeloMiniSerializer):
    pronto = serializers.BooleanField(help_text='Versão vigente aprovada pela Meta.')


class LimitesCobrancaSerializer(CrmSerializer):
    intervalo_dias_max = serializers.IntegerField()
    insistencias_max = serializers.IntegerField()
    teto_diario_max = serializers.IntegerField()


class CobrancaConfigSerializer(CrmSerializer):
    configuracao = CobrancaValoresSerializer()
    etapas = EtapaConfigSerializer(many=True)
    modelos = ModeloOpcaoSerializer(many=True)
    limites = LimitesCobrancaSerializer()


class PausarSerializer(CrmSerializer):
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=255)


# --- agenda ----------------------------------------------------------------------------------------

class AgendaQuerySerializer(CrmSerializer):
    dias = serializers.IntegerField(required=False, default=agenda.DIAS_PADRAO, min_value=0, max_value=agenda.MAX_DIAS,
                                    help_text='Hoje + os próximos N dias (padrão 7, máximo 14).')


class AgendaDiaQuerySerializer(_Paginacao):
    etapa = serializers.ChoiceField(choices=list(agenda.ORDEM), required=False, allow_blank=True)
    situacao = serializers.ChoiceField(choices=['previsto', 'excluido'], required=False, allow_blank=True)
    motivo = serializers.CharField(required=False, allow_blank=True, max_length=40)


class EtapaDiaSerializer(CrmSerializer):
    etapa = serializers.ChoiceField(choices=list(agenda.ORDEM))
    rotulo = serializers.CharField()
    previstos = serializers.IntegerField()
    excluidos = serializers.IntegerField()
    custo_estimado = serializers.CharField()
    enviados = serializers.IntegerField(help_text='Só hoje: avisos desta etapa que já saíram.')


class DiaAgendaSerializer(CrmSerializer):
    data = serializers.DateField()
    dia_semana = serializers.CharField()
    bloqueio = serializers.CharField(help_text='"" ou o motivo de nada sair no dia.')
    bloqueio_display = serializers.CharField()
    capacidade = serializers.IntegerField(help_text='Teto do dia (hoje: o que resta).')
    previstos = serializers.IntegerField()
    excluidos = serializers.IntegerField()
    custo_estimado = serializers.CharField()
    etapas = EtapaDiaSerializer(many=True)
    motivos = MotivoContagemSerializer(many=True)


class TotaisAgendaSerializer(CrmSerializer):
    previstos = serializers.IntegerField()
    custo_estimado = serializers.CharField()


class AgendaSerializer(CrmSerializer):
    gerado_em = serializers.DateTimeField()
    teto_efetivo = serializers.IntegerField()
    custo_por_mensagem = serializers.CharField()
    dias = DiaAgendaSerializer(many=True)
    totais = TotaisAgendaSerializer()


class ItemAgendaSerializer(CrmSerializer):
    parcela_id = serializers.IntegerField()
    cliente = ClienteMiniCobrancaSerializer()
    parcela = ParcelaMiniSerializer()
    etapa = serializers.ChoiceField(choices=list(agenda.ORDEM))
    etapa_display = serializers.CharField()
    situacao = serializers.ChoiceField(choices=['previsto', 'excluido'])
    motivo = serializers.CharField()
    motivo_display = serializers.CharField()
    telefone = serializers.CharField(help_text='Mascarado: (91) *****-0000. Vazio sem número válido.')


# --- histórico -------------------------------------------------------------------------------------

class HistoricoQuerySerializer(_Paginacao):
    desde = serializers.DateField(required=False, help_text='Padrão: 30 dias atrás.')
    ate = serializers.DateField(required=False, help_text='Padrão: hoje.')
    etapa = serializers.ChoiceField(choices=list(historico.ETAPAS), required=False, allow_blank=True)
    resultado = serializers.ChoiceField(choices=TentativaContato.Resultado.values, required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=list(historico.StatusEnvio.ROTULOS), required=False, allow_blank=True)
    disparo = serializers.IntegerField(required=False, min_value=1)

    def validate(self, dados: dict) -> dict:
        hoje = timezone.localdate()
        ate = dados.get('ate') or hoje
        desde = dados.get('desde') or ate - timedelta(days=DIAS_HISTORICO_PADRAO)
        if desde > ate:
            raise serializers.ValidationError({'desde': ['A data inicial não pode ser depois da final.']})
        if (ate - desde).days > MAX_DIAS_HISTORICO:
            raise serializers.ValidationError({'desde': [f'Use um período de até {MAX_DIAS_HISTORICO} dias.']})
        return {**dados, 'desde': desde, 'ate': ate}


class ItemHistoricoSerializer(CrmSerializer):
    id = serializers.IntegerField()
    criado_em = serializers.DateTimeField()
    cliente = ClienteMiniCobrancaSerializer()
    parcela = ParcelaMiniSerializer(allow_null=True)
    etapa = serializers.CharField()
    etapa_display = serializers.CharField()
    origem = serializers.ChoiceField(choices=['regua', 'disparo'])
    disparo_id = serializers.IntegerField(allow_null=True)
    telefone = serializers.CharField()
    status = serializers.ChoiceField(choices=list(historico.StatusEnvio.ROTULOS))
    status_display = serializers.CharField()
    resultado = serializers.CharField()
    resultado_display = serializers.CharField()
    respondido_em = serializers.DateTimeField(allow_null=True)
    conversa_id = serializers.IntegerField(allow_null=True)


class ResumoHistoricoSerializer(CrmSerializer):
    total = serializers.IntegerField()
    por_etapa = serializers.DictField(child=serializers.IntegerField())
    por_status = serializers.DictField(child=serializers.IntegerField())
    por_resultado = serializers.DictField(child=serializers.IntegerField())
