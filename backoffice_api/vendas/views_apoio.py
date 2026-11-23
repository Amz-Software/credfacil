"""Produtos vendidos e autorização de desconto pelo gerente."""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.exceptions import MethodNotAllowed, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle

from core.seguranca import mensagem_bloqueio

from ..nucleo.erros import LIMITE_EXCEDIDO, PROIBIDO_ACESSO, ErroBackoffice
from ..nucleo.escopo import tem_acesso_global
from ..nucleo.permissoes import QualquerPermissao
from ..nucleo.views import BackofficeAPIView
from .consultas import (
    ORDENACAO_PRODUTOS_VENDIDOS,
    filtrar_produtos_vendidos,
    ordenar,
    produtos_vendidos,
    vendas_anotadas,
)
from .entradas import AutorizacaoGerenteSerializer, validar_entrada
from .serializers import ProdutoVendidoSerializer, ReferenciaVendaSerializer, UsuarioDaVendaSerializer
from .servicos_acoes import AutorizacaoBloqueada, AutorizacaoNegada, autorizar_gerente
from .views_arquivos import TAGS

PERMISSAO_TODOS_OS_PRODUTOS_VENDIDOS = 'vendas.can_view_all_products_sold'


class MetodoNaoPermitidoMixin:
    """Método sem handler responde 405 antes das permissões declaradas (que dariam 403)."""

    def initial(self, request, *args, **kwargs):
        if request.method != 'OPTIONS' and not hasattr(self, request.method.lower()):
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)


class ProdutosVendidosView(MetodoNaoPermitidoMixin, BackofficeAPIView):
    permissoes = {'GET': ['vendas.view_produtovenda']}
    permissao_global_lojas = PERMISSAO_TODOS_OS_PRODUTOS_VENDIDOS

    @extend_schema(
        tags=TAGS,
        summary='Produtos vendidos',
        parameters=[
            OpenApiParameter('nome', str, description='Nome do produto (contém)'),
            OpenApiParameter('cpf', str, description='CPF do cliente (só dígitos, contém)'),
            OpenApiParameter('imei', str),
            OpenApiParameter('loja', int, description='Só para quem vê os produtos vendidos de todas as lojas'),
            OpenApiParameter('canceladas', bool, description='Sem o filtro: todas as vendas'),
            OpenApiParameter('data_inicio', OpenApiTypes.DATE),
            OpenApiParameter('data_fim', OpenApiTypes.DATE),
            OpenApiParameter('ordenar', str, description='Campos: ' + ', '.join(sorted(ORDENACAO_PRODUTOS_VENDIDOS))),
        ],
        responses=ProdutoVendidoSerializer(many=True),
    )
    def get(self, request):
        pode_filtrar_loja = tem_acesso_global(request.user, self.permissao_global_lojas)
        queryset = self.filtrar_por_lojas(produtos_vendidos(), 'venda__loja')
        queryset = filtrar_produtos_vendidos(queryset, request.query_params, pode_filtrar_loja=pode_filtrar_loja)
        queryset = ordenar(queryset, request.query_params.get('ordenar'), ORDENACAO_PRODUTOS_VENDIDOS, '-data_venda')
        return self.paginar(queryset, ProdutoVendidoSerializer)


RESPOSTA_AUTORIZACAO = inline_serializer('AutorizacaoGerente', {
    'autorizado': serializers.BooleanField(),
    'gerente': UsuarioDaVendaSerializer(),
    'loja': ReferenciaVendaSerializer(),
})


class AutorizacaoGerenteView(MetodoNaoPermitidoMixin, BackofficeAPIView):
    """Confere usuário/senha de um gerente da loja (desconto acima do limite). Não cria sessão."""

    permissoes = {'POST': [QualquerPermissao('vendas.change_venda', 'vendas.add_venda')]}
    permissao_global_lojas = 'vendas.can_view_all_sales'
    throttle_classes = [UserRateThrottle, ScopedRateThrottle]
    throttle_scope = 'login'

    def _loja(self, entrada: dict):
        if entrada.get('venda') is not None:
            venda = self.filtrar_por_lojas(vendas_anotadas()).filter(pk=entrada['venda']).first()
            if venda is None or venda.loja is None:
                raise ValidationError({'venda': ['Venda não encontrada.']})
            return venda.loja
        lojas = self.lojas()
        if entrada.get('loja') is not None:
            loja = lojas.filter(pk=entrada['loja']).first()
            if loja is None:
                raise ErroBackoffice('Você não tem acesso a esta loja.', codigo=PROIBIDO_ACESSO, status_http=403)
            return loja
        if lojas.count() == 1:
            return lojas.get()
        raise ValidationError({'loja': ['Informe a venda ou a loja da autorização.']})

    @extend_schema(tags=TAGS, summary='Autorização de gerente', request=AutorizacaoGerenteSerializer,
                   responses=RESPOSTA_AUTORIZACAO)
    def post(self, request):
        entrada = validar_entrada(AutorizacaoGerenteSerializer, request.data)
        loja = self._loja(entrada)
        dados = {'usuario_informado': entrada['usuario'], 'loja': loja.pk, 'venda': entrada.get('venda')}
        try:
            gerente = autorizar_gerente(request, entrada['usuario'], entrada['senha'], loja)
        except AutorizacaoBloqueada:
            self.auditar('autorizacao_gerente_negada', objeto=loja, dados={**dados, 'motivo': 'bloqueado'})
            raise ErroBackoffice(mensagem_bloqueio(), codigo=LIMITE_EXCEDIDO, status_http=429)
        except AutorizacaoNegada as negada:
            self.auditar('autorizacao_gerente_negada', objeto=loja, dados={**dados, 'motivo': negada.motivo})
            raise ErroBackoffice(negada.mensagem, codigo=PROIBIDO_ACESSO, status_http=403)
        self.auditar('autorizacao_gerente_concedida', objeto=loja, dados={**dados, 'gerente': gerente.pk})
        return Response({
            'autorizado': True,
            'gerente': UsuarioDaVendaSerializer(gerente).data,
            'loja': {'id': loja.pk, 'nome': loja.nome},
        })
