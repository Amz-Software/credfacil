"""Dados de apoio da caixa de entrada: contexto, etiquetas, respostas rápidas, aberturas, atendentes e clientes."""
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from crm.models import LIMITE_TEXTO, Conversa, Etiqueta, RespostaRapida
from crm.permissoes import pode_gerenciar, usuarios_com_acesso
from crm.services import aberturas, envio, midias, organizacao
from crm.web.filtros import FILAS, ORDENS

from ..base import CrmAPIView, obter_conversa
from ..permissoes import ACESSO
from ..serializers.entrada import BuscaClientesQuerySerializer
from ..serializers.saida import (
    AberturaDisponivelSerializer, AtendenteSerializer, BuscaClientesSerializer, ContextoSerializer,
    EtiquetaMiniSerializer, RespostaRapidaMiniSerializer,
)
from ..servicos import simulado
from . import TAGS

PERM_VER_CLIENTE = 'vendas.view_cliente'
PERM_VER_PAGAMENTO = 'vendas.view_pagamento'


def _opcoes(escolhas) -> list[dict]:
    return [{'valor': valor, 'rotulo': rotulo} for valor, rotulo in escolhas]


class _CatalogoView(CrmAPIView):
    """Lista curta e completa (sem paginação) para selects da caixa de entrada."""

    permissoes = {'GET': ACESSO}
    pagination_class = None


class ContextoView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS, summary='Permissões, opções dos filtros e limites da caixa de entrada',
                   responses=ContextoSerializer)
    def get(self, request):
        usuario = request.user
        return Response(ContextoSerializer({
            'simulado': simulado(),
            'pode_gerenciar': pode_gerenciar(usuario),
            've_clientes': usuario.has_perm(PERM_VER_CLIENTE),
            've_pagamentos': usuario.has_perm(PERM_VER_PAGAMENTO),
            'filas': _opcoes(FILAS),
            'ordens': _opcoes(ORDENS),
            'situacoes': _opcoes(Conversa.Situacao.choices),
            'cores_etiqueta': _opcoes(Etiqueta.Cor.choices),
            'limites': {
                'texto': LIMITE_TEXTO, 'legenda': envio.LIMITE_LEGENDA, 'arquivo_bytes': midias.LIMITE_ENVIO,
                'nota': organizacao.LIMITE_NOTA, 'apelido': organizacao.LIMITE_APELIDO,
                'lembrete': organizacao.LIMITE_LEMBRETE,
            },
        }).data)


class EtiquetasView(_CatalogoView):
    @extend_schema(tags=TAGS, summary='Etiquetas ativas (filtro e seleção)', responses=EtiquetaMiniSerializer(many=True))
    def get(self, request):
        return Response(EtiquetaMiniSerializer(Etiqueta.objects.filter(ativo=True), many=True).data)


class RespostasRapidasView(_CatalogoView):
    @extend_schema(tags=TAGS, summary='Respostas rápidas ativas (texto com marcadores; use a prévia para preencher)',
                   responses=RespostaRapidaMiniSerializer(many=True))
    def get(self, request):
        return Response(RespostaRapidaMiniSerializer(RespostaRapida.objects.filter(ativo=True), many=True).data)


class AberturasView(_CatalogoView):
    @extend_schema(tags=TAGS, summary='Mensagens de abertura ativas (nova conversa e janela fechada)',
                   responses=AberturaDisponivelSerializer(many=True))
    def get(self, request):
        return Response(AberturaDisponivelSerializer(aberturas.disponiveis(), many=True).data)


class AtendentesView(_CatalogoView):
    @extend_schema(tags=TAGS, summary='Quem atende no CRM (atribuir e lembrete)', responses=AtendenteSerializer(many=True))
    def get(self, request):
        atendentes = usuarios_com_acesso().order_by('first_name', 'username')
        return Response(AtendenteSerializer(atendentes, many=True).data)


class ClientesView(CrmAPIView):
    """Busca por CPF ou nome no escopo de lojas do usuário (mesma regra das telas)."""

    permissoes = {'GET': [*ACESSO, PERM_VER_CLIENTE]}

    @extend_schema(tags=TAGS, summary='Buscar cliente para vincular (CPF ou nome, mín. 3 caracteres)',
                   parameters=[BuscaClientesQuerySerializer], responses=BuscaClientesSerializer)
    def get(self, request):
        params = self.validar_query(BuscaClientesQuerySerializer)
        termo = params['busca'].strip()
        vinculados = set()
        if params.get('conversa'):
            vinculados = set(obter_conversa(params['conversa']).clientes.values_list('id', flat=True))
        achados = [c for c in organizacao.buscar_clientes(request.user, termo) if c['id'] not in vinculados]
        return Response(BuscaClientesSerializer({
            'results': achados, 'busca_curta': len(termo) < organizacao.MIN_BUSCA_CLIENTE,
        }).data)
