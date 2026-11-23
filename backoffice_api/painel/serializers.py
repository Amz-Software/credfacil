"""Filtros e formatos de resposta do painel (também descrevem o esquema OpenAPI)."""
from rest_framework import serializers

from vendas.models import Loja

MAX_DIGITOS = 14


def _dinheiro(**kwargs) -> serializers.DecimalField:
    return serializers.DecimalField(max_digits=MAX_DIGITOS, decimal_places=2, **kwargs)


# ── Filtros ─────────────────────────────────────────────────────────────────

class FiltrosGraficosSerializer(serializers.Serializer):
    """`?loja=&data_inicio=&data_fim=`; a loja precisa estar no escopo da requisição."""

    loja = serializers.PrimaryKeyRelatedField(queryset=Loja.objects.none(), required=False, allow_null=True)
    data_inicio = serializers.DateField(required=False, allow_null=True)
    data_fim = serializers.DateField(required=False, allow_null=True)

    def __init__(self, *args, lojas=None, **kwargs):
        super().__init__(*args, **kwargs)
        if lojas is not None:
            self.fields['loja'].queryset = lojas

    def validate(self, attrs):
        inicio, fim = attrs.get('data_inicio'), attrs.get('data_fim')
        if inicio and fim and inicio > fim:
            raise serializers.ValidationError({'data_fim': ['A data final deve ser igual ou posterior à inicial.']})
        return attrs


# ── Respostas ───────────────────────────────────────────────────────────────

class LojaResumoSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    nome = serializers.CharField()


class SituacaoCarteiraSerializer(serializers.Serializer):
    total_pagamentos = serializers.IntegerField()
    parcelas_vencidas = serializers.IntegerField()
    valor_vencido = _dinheiro()
    parcelas_a_vencer = serializers.IntegerField()
    valor_a_vencer = _dinheiro()


class GraficoBalancoSerializer(serializers.Serializer):
    unidade = serializers.CharField()
    rotulos = serializers.ListField(child=serializers.CharField())
    valores = serializers.ListField(child=serializers.FloatField())


class KpisCarteiraSerializer(serializers.Serializer):
    parcelas_consideradas_por_venda = serializers.IntegerField()
    total_vendas = serializers.IntegerField()
    total_parcelas = serializers.IntegerField()
    valor_total = _dinheiro()
    parcelas_pagas = serializers.IntegerField()
    valor_pago = _dinheiro()
    parcelas_vencidas = serializers.IntegerField()
    valor_vencido = _dinheiro()
    parcelas_a_vencer = serializers.IntegerField()
    valor_a_vencer = _dinheiro()
    desativados = SituacaoCarteiraSerializer()
    grafico_balanco = GraficoBalancoSerializer()


class ContagemStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    rotulo = serializers.CharField()
    total = serializers.IntegerField()


class FilaCreditoSerializer(serializers.Serializer):
    por_status = ContagemStatusSerializer(many=True)
    total = serializers.IntegerField()
    em_espera = serializers.IntegerField()
    tempo_medio_espera_minutos = serializers.IntegerField(allow_null=True)
    maior_espera_minutos = serializers.IntegerField(allow_null=True)


class InadimplenciaSerializer(serializers.Serializer):
    parcelas_atrasadas = serializers.IntegerField()
    valor_em_atraso = _dinheiro()
    pagamentos_em_atraso = serializers.IntegerField()
    clientes_inadimplentes = serializers.IntegerField()


class AtalhoSerializer(serializers.Serializer):
    id = serializers.CharField()
    titulo = serializers.CharField()
    descricao = serializers.CharField()


class ResumoPainelSerializer(serializers.Serializer):
    loja = LojaResumoSerializer(allow_null=True, help_text='Preenchida quando o recorte é de uma loja só.')
    quantidade_lojas = serializers.IntegerField()
    kpis = KpisCarteiraSerializer(allow_null=True, help_text='Só com vendas.can_view_your_dashboard.')
    analise = FilaCreditoSerializer(allow_null=True, help_text='Só com vendas.view_cliente.')
    financeiro = InadimplenciaSerializer(allow_null=True, help_text='Só com vendas.view_pagamento.')
    atalhos = AtalhoSerializer(many=True)


class ResumoGraficosSerializer(serializers.Serializer):
    total_vendas = serializers.IntegerField()
    total_parcelas = serializers.IntegerField()
    valor_total_parcelas = _dinheiro()
    total_repasses = _dinheiro()
    parcelas_pagas = serializers.IntegerField()
    valor_pago = _dinheiro()
    parcelas_vencidas = serializers.IntegerField()
    valor_vencido = _dinheiro()
    parcelas_a_vencer = serializers.IntegerField()
    valor_a_vencer = _dinheiro()
    clientes_vencidos = serializers.IntegerField()
    clientes_quitados = serializers.IntegerField()
    cobranca = SituacaoCarteiraSerializer()
    desativados = SituacaoCarteiraSerializer()


class RepasseLojaSerializer(serializers.Serializer):
    loja = LojaResumoSerializer()
    valor = _dinheiro()


class SerieLojaSerializer(serializers.Serializer):
    id = serializers.CharField()
    rotulo = serializers.CharField()
    percentuais = serializers.ListField(child=serializers.FloatField())
    valores = serializers.ListField(child=serializers.FloatField())


class GraficoPorLojaSerializer(serializers.Serializer):
    lojas = LojaResumoSerializer(many=True)
    rotulos = serializers.ListField(child=serializers.CharField())
    totais = serializers.ListField(child=serializers.FloatField())
    series = SerieLojaSerializer(many=True)


class SerieMensalSerializer(serializers.Serializer):
    loja = LojaResumoSerializer()
    situacao = serializers.ChoiceField(choices=['pago', 'vencido', 'a_vencer'])
    rotulo = serializers.CharField()
    percentuais = serializers.ListField(child=serializers.IntegerField())
    valores = serializers.ListField(child=serializers.FloatField())
    totais = serializers.ListField(child=serializers.FloatField())


class GraficoMensalSerializer(serializers.Serializer):
    rotulos = serializers.ListField(child=serializers.CharField(), help_text='Meses no formato AAAA-MM.')
    series = SerieMensalSerializer(many=True)


class FiltrosAplicadosSerializer(serializers.Serializer):
    loja = serializers.IntegerField(allow_null=True)
    data_inicio = serializers.DateField(allow_null=True)
    data_fim = serializers.DateField(allow_null=True)


class GraficosSerializer(serializers.Serializer):
    filtros = FiltrosAplicadosSerializer()
    lojas_disponiveis = LojaResumoSerializer(many=True)
    resumo = ResumoGraficosSerializer()
    repasses_por_loja = RepasseLojaSerializer(many=True)
    por_loja = GraficoPorLojaSerializer()
    por_loja_mes = GraficoMensalSerializer(allow_null=True, help_text='Só quando o recorte é de uma loja.')
