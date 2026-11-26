"""Detalhe completo da solicitação (cliente + análise) para o analista."""
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..acoes_disponiveis import acoes_disponiveis
from ..notificar_vendedor import ultimo_aviso
from ..arquivos import ARQUIVOS_SOLICITACAO
from ..edicao import campos_editaveis, pode_editar
from ..linha_do_tempo import montar_linha_do_tempo
from ..regras import ETAPAS, etapa_da_analise, pode_ver_numero_autenticador, pode_ver_serasa
from ..simulacao import simular_parcelamento
from .comum import (
    DINHEIRO,
    CreditoLojaRefSerializer,
    CreditoProdutoDetalheSerializer,
    CreditoUsuarioRefSerializer,
    usuario_da_requisicao,
)
from .estruturas import (
    CreditoAcoesSerializer,
    CreditoComprovantesSerializer,
    CreditoEdicaoSerializer,
    CreditoEventoSerializer,
    CreditoIcloudSerializer,
    CreditoImeiRefSerializer,
    CreditoNumeroAutenticadorSerializer,
    CreditoSimulacaoSerializer,
    CreditoVendaRefSerializer,
)
from .solicitacao_lista import CENTAVOS, entrada_da_analise, numero_parcelas


def url_arquivo(cliente_id: int, campo: str) -> str:
    return reverse('backoffice_api:credito:solicitacao-arquivo', kwargs={'pk': cliente_id, 'campo': campo})


class CreditoDadosClienteSerializer(serializers.Serializer):
    nome = serializers.CharField()
    email = serializers.CharField(allow_null=True)
    telefone = serializers.CharField()
    telefone_secundario = serializers.CharField()
    cpf = serializers.CharField()
    nascimento = serializers.DateField()
    rg = serializers.CharField()
    cep = serializers.CharField()
    endereco = serializers.CharField()
    bairro = serializers.CharField()
    cidade = serializers.CharField()
    profissao = serializers.CharField()
    quantidade_dependentes = serializers.IntegerField()
    recebe_auxilio = serializers.BooleanField()
    total_renda = serializers.DecimalField(**DINHEIRO)
    observacao_cliente = serializers.CharField()


class CreditoContatoAdicionalSerializer(serializers.Serializer):
    nome = serializers.CharField(source='nome_adicional', allow_null=True)
    contato = serializers.CharField(allow_null=True)
    endereco = serializers.CharField(source='endereco_adicional', allow_null=True)
    obteve_contato = serializers.BooleanField()


class CreditoInformacaoPessoalSerializer(serializers.Serializer):
    nome = serializers.CharField(allow_null=True)
    contato = serializers.CharField(allow_null=True)
    endereco = serializers.CharField(allow_null=True)
    obteve_contato = serializers.BooleanField()


class CreditoAnaliseDetalheSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.CharField()
    status_rotulo = serializers.CharField(source='get_status_display')
    status_app = serializers.CharField(source='status_aplicativo')
    status_app_rotulo = serializers.CharField(source='get_status_aplicativo_display')
    etapa = serializers.SerializerMethodField()
    etapa_rotulo = serializers.SerializerMethodField()
    data_analise = serializers.DateTimeField()
    data_aprovacao = serializers.DateTimeField(allow_null=True)
    data_reprovacao = serializers.DateTimeField(allow_null=True)
    data_cancelamento = serializers.DateTimeField(allow_null=True)
    aprovado_por = CreditoUsuarioRefSerializer(allow_null=True)
    vendedor = CreditoUsuarioRefSerializer(source='criado_por', allow_null=True)
    analise_online = serializers.BooleanField()
    comodato = serializers.BooleanField(help_text='Aparelho de comodato: a venda não tem repasse ao lojista.')
    segunda_compra = serializers.BooleanField()
    observacao = serializers.CharField(allow_null=True)
    data_pagamento = serializers.CharField(allow_null=True)
    numero_parcelas = serializers.SerializerMethodField()
    entrada_informada = serializers.DecimalField(allow_null=True, **DINHEIRO)
    entrada = serializers.SerializerMethodField()
    produto = CreditoProdutoDetalheSerializer()
    imei = CreditoImeiRefSerializer(allow_null=True)
    imei_informado = serializers.CharField(allow_null=True)
    imei_ultimos_digitos_vendedor = serializers.CharField(allow_null=True)
    numero_autenticador = serializers.SerializerMethodField(help_text='Só para ANALISTA/ADMINISTRADOR.')
    icloud = serializers.SerializerMethodField()

    def get_etapa(self, analise) -> str:
        return etapa_da_analise(analise)

    def get_etapa_rotulo(self, analise) -> str:
        return ETAPAS[etapa_da_analise(analise)]

    def get_numero_parcelas(self, analise) -> int | None:
        return numero_parcelas(analise)

    def get_entrada(self, analise) -> str:
        return str(entrada_da_analise(analise).quantize(CENTAVOS))

    @extend_schema_field(CreditoNumeroAutenticadorSerializer(allow_null=True))
    def get_numero_autenticador(self, analise):
        user = usuario_da_requisicao(self)
        if not (user and pode_ver_numero_autenticador(user)) or analise.numero_autenticador is None:
            return None
        return CreditoNumeroAutenticadorSerializer(analise.numero_autenticador).data

    @extend_schema_field(CreditoIcloudSerializer)
    def get_icloud(self, analise):
        return {
            'email': analise.email_icloud,
            'configurado_vendedor': analise.icloud_configurado_vendedor,
            'confirmado_analista': analise.icloud_confirmado_analista,
        }


def _comprovantes(cliente, user) -> dict:
    comprovantes, analise = cliente.comprovantes, cliente.analise_credito
    ver_serasa = pode_ver_serasa(user)
    arquivos = []
    for definicao in ARQUIVOS_SOLICITACAO.values():
        if definicao.serasa and not ver_serasa:
            continue
        origem = comprovantes if definicao.origem == 'comprovantes' else analise
        arquivo = getattr(origem, definicao.campo)
        presente = bool(arquivo and arquivo.name)
        arquivos.append({
            'campo': definicao.campo,
            'rotulo': definicao.rotulo,
            'presente': presente,
            'url': url_arquivo(cliente.pk, definicao.campo) if presente else None,
            'analisado': getattr(comprovantes, f'{definicao.campo}_analise', None),
            'serasa': definicao.serasa,
        })
    return {'arquivos': arquivos, 'restricao': comprovantes.restricao if ver_serasa else None}


class CreditoSolicitacaoDetalheSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    analise_id = serializers.IntegerField(source='analise_credito.id')
    cliente = CreditoDadosClienteSerializer(source='*')
    loja = CreditoLojaRefSerializer(allow_null=True)
    contato_adicional = CreditoContatoAdicionalSerializer(allow_null=True)
    informacao_pessoal = CreditoInformacaoPessoalSerializer(allow_null=True)
    comprovantes = serializers.SerializerMethodField()
    analise = CreditoAnaliseDetalheSerializer(source='analise_credito')
    parcelamento = serializers.SerializerMethodField()
    venda = CreditoVendaRefSerializer(source='analise_credito.venda', allow_null=True)
    linha_do_tempo = serializers.SerializerMethodField()
    acoes = serializers.SerializerMethodField()
    vendedor_notificado_em = serializers.SerializerMethodField(
        help_text='Último uso do botão "Notificar vendedor" (o botão volta após 30 s).',
    )
    edicao = serializers.SerializerMethodField()

    @extend_schema_field(CreditoComprovantesSerializer)
    def get_comprovantes(self, cliente):
        return _comprovantes(cliente, usuario_da_requisicao(self))

    @extend_schema_field(CreditoSimulacaoSerializer)
    def get_parcelamento(self, cliente):
        return simular_parcelamento(cliente.analise_credito)

    @extend_schema_field(CreditoEventoSerializer(many=True))
    def get_linha_do_tempo(self, cliente):
        return montar_linha_do_tempo(cliente, usuario_da_requisicao(self))

    @extend_schema_field(CreditoAcoesSerializer)
    def get_acoes(self, cliente):
        return acoes_disponiveis(usuario_da_requisicao(self), cliente.analise_credito)

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_vendedor_notificado_em(self, cliente):
        ultimo = ultimo_aviso(cliente.analise_credito)
        return ultimo.isoformat() if ultimo else None

    @extend_schema_field(CreditoEdicaoSerializer)
    def get_edicao(self, cliente):
        user = usuario_da_requisicao(self)
        return {'pode_editar': pode_editar(cliente, user), 'campos_editaveis': campos_editaveis(cliente, user)}
