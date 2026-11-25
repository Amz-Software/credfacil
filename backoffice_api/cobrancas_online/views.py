"""Pagamentos online (PagBank) no backoffice: configuração, cobranças, link para o cliente e registros."""
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from pagamentos_online.models import Cobranca, ConfiguracaoPagamentoOnline, RegistroPagBank
from pagamentos_online.publico.dados import opcoes_do_plano
from pagamentos_online.publico.views import CobrancaAgrupadaEntrada, ids_da_query
from pagamentos_online.servicos.cobrancas import (
    gerar_cobranca, gerar_cobranca_agrupada, opcoes_da_parcela, plano_para_exibir, quitacao_do_pagamento,
)
from pagamentos_online.servicos.links import enviar_link_whatsapp, link_do_pagamento

from ..financeiro.base import ContasAReceberBaseView
from ..financeiro.constantes import GRUPOS_ANALISTA_ADMIN
from ..nucleo.erros import ErroBackoffice
from ..nucleo.permissoes import EmGrupo
from .serializers import CobrancaSerializer, ConfiguracaoSerializer, GerarCobrancaSerializer, RegistroSerializer

TAGS = ['bo-cobrancas-online']
ANALISTA_OU_ADMIN = EmGrupo(*GRUPOS_ANALISTA_ADMIN)
SO_ADMIN = EmGrupo('ADMINISTRADOR')
FILTROS_SIMPLES = ('status', 'forma', 'origem')


def _cobrancas():
    return (Cobranca.objects.select_related('parcela__pagamento__venda__cliente', 'criado_por')
            .prefetch_related('itens__parcela'))


@extend_schema(tags=TAGS)
class ConfiguracaoView(ContasAReceberBaseView):
    permissoes = {'GET': [ANALISTA_OU_ADMIN], 'PATCH': [SO_ADMIN]}

    @extend_schema(responses=ConfiguracaoSerializer)
    def get(self, request):
        return Response(ConfiguracaoSerializer(ConfiguracaoPagamentoOnline.obter()).data)

    @extend_schema(request=ConfiguracaoSerializer, responses=ConfiguracaoSerializer)
    def patch(self, request):
        configuracao = ConfiguracaoPagamentoOnline.obter()
        entrada = ConfiguracaoSerializer(configuracao, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        antes = ConfiguracaoSerializer(configuracao).data
        configuracao = entrada.save(modificado_por=request.user)
        depois = ConfiguracaoSerializer(configuracao).data
        alteracoes = {c: {'antes': antes[c], 'depois': depois[c]} for c in entrada.validated_data if antes[c] != depois[c]}
        if alteracoes:
            self.auditar('pagamento_online_configurado', objeto=configuracao, dados={'alteracoes': alteracoes})
        return Response(depois)


@extend_schema(tags=TAGS)
class CobrancasListaView(ContasAReceberBaseView):
    """Todas as cobranças online, com filtros de status, forma, origem, duplicidade e busca por cliente."""

    permissoes = {'GET': [ANALISTA_OU_ADMIN]}

    @extend_schema(responses=CobrancaSerializer(many=True))
    def get(self, request):
        cobrancas = self.filtrar_por_lojas(_cobrancas(), 'parcela__pagamento__loja')
        for campo in FILTROS_SIMPLES:
            valor = request.query_params.get(campo)
            if valor:
                cobrancas = cobrancas.filter(**{campo: valor})
        if request.query_params.get('duplicado') in ('1', 'true'):
            cobrancas = cobrancas.filter(pagamento_duplicado=True)
        if request.query_params.get('acerto') in ('1', 'true'):
            cobrancas = cobrancas.exclude(acerto_manual='')
        busca = (request.query_params.get('busca') or '').strip()
        if busca:
            cobrancas = cobrancas.filter(
                Q(parcela__pagamento__venda__cliente__nome__icontains=busca)
                | Q(parcela__pagamento__venda__cliente__cpf__startswith=busca)
                | Q(pagbank_id=busca) | Q(pagbank_pedido_id=busca)
            )
        return self.paginar(cobrancas.order_by('-criado_em', '-id'), CobrancaSerializer)


@extend_schema(tags=TAGS)
class ParcelaCobrancasView(ContasAReceberBaseView):
    """GET: cobranças, opções com taxa e link do cliente. POST: gera uma cobrança (Pix, boleto ou cartão)."""

    permissoes = {'GET': [ANALISTA_OU_ADMIN], 'POST': [ANALISTA_OU_ADMIN, 'vendas.change_pagamento']}

    def get(self, request, pk: int):
        parcela = self.obter_parcela(pk)
        cobrancas = (_cobrancas().filter(Q(parcela=parcela) | Q(itens__parcela=parcela))
                     .distinct().order_by('-criado_em', '-id'))
        return Response({
            'cobrancas': CobrancaSerializer(cobrancas, many=True).data,
            'opcoes': [opcao.como_dict() for opcao in opcoes_da_parcela(parcela)],
            'link_cliente': link_do_pagamento(parcela.pagamento, parcela),
        })

    @extend_schema(request=GerarCobrancaSerializer, responses={201: CobrancaSerializer})
    def post(self, request, pk: int):
        parcela = self.obter_parcela(pk)
        entrada = GerarCobrancaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        cobranca = gerar_cobranca(parcela, entrada.validated_data['forma'], Cobranca.Origem.BACKOFFICE, request.user)
        self.auditar('cobranca_online_gerada', objeto=parcela,
                     dados={'cobranca_id': cobranca.pk, 'forma': cobranca.forma, 'valor_total': str(cobranca.valor_total)})
        return Response(CobrancaSerializer(_cobrancas().get(pk=cobranca.pk)).data, status=201)


@extend_schema(tags=TAGS)
class PagamentoCobrancasView(ContasAReceberBaseView):
    """GET: cobranças da compra e a quitação online. POST: cobrança de várias parcelas ou da quitação."""

    permissoes = {'GET': [ANALISTA_OU_ADMIN], 'POST': [ANALISTA_OU_ADMIN, 'vendas.change_pagamento']}

    def get(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        cobrancas = _cobrancas().filter(parcela__pagamento=pagamento).order_by('-criado_em', '-id')
        quitacao = quitacao_do_pagamento(pagamento)
        return Response({
            'cobrancas': CobrancaSerializer(cobrancas, many=True).data,
            'quitacao': opcoes_do_plano(quitacao) if quitacao else None,
            'link_cliente': link_do_pagamento(pagamento),
        })

    @extend_schema(request=CobrancaAgrupadaEntrada, responses={201: CobrancaSerializer})
    def post(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        entrada = CobrancaAgrupadaEntrada(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        cobranca = gerar_cobranca_agrupada(pagamento, dados['forma'], Cobranca.Origem.BACKOFFICE,
                                           dados.get('parcelas'), dados['quitacao'], request.user)
        self.auditar('cobranca_online_gerada', objeto=pagamento, dados={
            'cobranca_id': cobranca.pk, 'tipo': cobranca.tipo, 'forma': cobranca.forma,
            'valor_total': str(cobranca.valor_total),
        })
        return Response(CobrancaSerializer(_cobrancas().get(pk=cobranca.pk)).data, status=201)


@extend_schema(tags=TAGS)
class PagamentoOpcoesView(ContasAReceberBaseView):
    """Valores e opções (com taxa) de `?parcelas=1,2` ou `?quitacao=1` antes de gerar."""

    permissoes = {'GET': [ANALISTA_OU_ADMIN]}

    def get(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        quitacao = request.query_params.get('quitacao') in ('1', 'true')
        ids = None if quitacao else ids_da_query(request.query_params.get('parcelas', ''))
        return Response(opcoes_do_plano(plano_para_exibir(pagamento, ids)))


@extend_schema(tags=TAGS)
class EnviarLinkView(ContasAReceberBaseView):
    """Manda o link de pagamento no WhatsApp do cliente (só com a janela de 24h aberta)."""

    permissoes = {'POST': [ANALISTA_OU_ADMIN]}

    def post(self, request, pk: int):
        parcela = self.obter_parcela(pk)
        link = enviar_link_whatsapp(parcela, request.user)
        # Sem o link no registro: ele contém o token de acesso do cliente.
        self.auditar('link_pagamento_enviado', objeto=parcela, dados={'pagamento_id': parcela.pagamento_id})
        return Response({'link': link, 'enviado': True})


@extend_schema(tags=TAGS)
class RegistrosView(ContasAReceberBaseView):
    """Requisições e respostas trocadas com o PagBank (para a homologação e para conferência)."""

    permissoes = {'GET': [SO_ADMIN]}

    @extend_schema(responses=RegistroSerializer(many=True))
    def get(self, request):
        registros = RegistroPagBank.objects.all()
        cobranca_id = request.query_params.get('cobranca')
        if cobranca_id:
            if not cobranca_id.isdigit():
                raise ErroBackoffice('Informe o número da cobrança.', campos={'cobranca': ['Número inválido.']})
            registros = registros.filter(cobranca=get_object_or_404(Cobranca, pk=int(cobranca_id)))
        tipo = request.query_params.get('tipo')
        if tipo:
            registros = registros.filter(tipo=tipo)
        return self.paginar(registros.order_by('-criado_em', '-id'), RegistroSerializer)
