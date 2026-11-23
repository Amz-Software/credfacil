"""Pré-análise rápida: item da lista e detalhe."""
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..arquivos import ARQUIVOS_PRE_ANALISE
from ..regras import PERMISSAO_DECIDIR, mascarar_cpf, pode_gerenciar_serasa_pre_analise
from .comum import CreditoLojaRefSerializer, CreditoUsuarioRefSerializer, usuario_da_requisicao
from .estruturas import CreditoArquivoSerializer


def url_arquivo_pre_analise(pre_id: int, campo: str) -> str:
    return reverse('backoffice_api:credito:pre-analise-arquivo', kwargs={'pk': pre_id, 'campo': campo})


class CreditoPreAnaliseListaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome_completo = serializers.CharField()
    cpf = serializers.SerializerMethodField(help_text='CPF mascarado (***.456.789-**).')
    loja = CreditoLojaRefSerializer(allow_null=True)
    status = serializers.CharField()
    status_rotulo = serializers.CharField(source='get_status_display')
    finalizada = serializers.BooleanField(help_text='Já virou proposta completa (cliente gerado).')
    cliente_gerado_id = serializers.IntegerField(allow_null=True)
    tem_consulta_serasa = serializers.BooleanField()
    tem_comprovante_residencia = serializers.BooleanField()
    possui_duas_referencias = serializers.BooleanField()
    segunda_compra = serializers.BooleanField()
    criado_por = CreditoUsuarioRefSerializer(allow_null=True)
    analisado_por = CreditoUsuarioRefSerializer(allow_null=True)
    data_decisao = serializers.DateTimeField(allow_null=True)
    criado_em = serializers.DateTimeField()

    def get_cpf(self, pre) -> str:
        return mascarar_cpf(pre.cpf)


class CreditoConsultaSerasaPreAnaliseSerializer(serializers.Serializer):
    presente = serializers.BooleanField()
    url = serializers.CharField(allow_null=True)
    anexada_por = CreditoUsuarioRefSerializer(allow_null=True)
    anexada_em = serializers.DateTimeField(allow_null=True)


class CreditoAcoesPreAnaliseSerializer(serializers.Serializer):
    aprovar = serializers.BooleanField()
    reprovar = serializers.BooleanField()
    gerenciar_serasa = serializers.BooleanField()


class CreditoPreAnaliseDetalheSerializer(CreditoPreAnaliseListaSerializer):
    cpf = serializers.CharField(help_text='CPF completo.')
    observacao = serializers.CharField(allow_null=True, help_text='Observação ou motivo da reprovação.')
    arquivos = serializers.SerializerMethodField()
    consulta_serasa = serializers.SerializerMethodField(help_text='Só para quem gerencia a consulta Serasa.')
    acoes = serializers.SerializerMethodField()

    def _pode_gerenciar(self) -> bool:
        user = usuario_da_requisicao(self)
        return bool(user and pode_gerenciar_serasa_pre_analise(user))

    @extend_schema_field(CreditoArquivoSerializer(many=True))
    def get_arquivos(self, pre):
        itens = []
        for definicao in ARQUIVOS_PRE_ANALISE.values():
            if definicao.serasa:
                continue
            presente = bool(getattr(pre, definicao.campo))
            itens.append({
                'campo': definicao.campo,
                'rotulo': definicao.rotulo,
                'presente': presente,
                'url': url_arquivo_pre_analise(pre.pk, definicao.campo) if presente else None,
                'analisado': None,
                'serasa': False,
            })
        return itens

    @extend_schema_field(CreditoConsultaSerasaPreAnaliseSerializer(allow_null=True))
    def get_consulta_serasa(self, pre):
        if not self._pode_gerenciar():
            return None
        anexada_por = pre.consulta_serasa_anexada_por
        return {
            'presente': pre.tem_consulta_serasa,
            'url': url_arquivo_pre_analise(pre.pk, 'consulta_serasa') if pre.tem_consulta_serasa else None,
            'anexada_por': CreditoUsuarioRefSerializer(anexada_por).data if anexada_por else None,
            'anexada_em': serializers.DateTimeField().to_representation(pre.consulta_serasa_anexada_em)
            if pre.consulta_serasa_anexada_em else None,
        }

    @extend_schema_field(CreditoAcoesPreAnaliseSerializer)
    def get_acoes(self, pre):
        user = usuario_da_requisicao(self)
        pendente = pre.status == 'P'
        decide = bool(user and user.has_perm(PERMISSAO_DECIDIR))
        return {
            'aprovar': decide and pendente,
            'reprovar': decide and pendente,
            'gerenciar_serasa': self._pode_gerenciar() and not pre.finalizada,
        }
