"""Disparos manuais de cobrança: modelos, prévia, lista, detalhe, destinatários, confirmar, cancelar, retomar.

Leitura com `crm.acessar_crm`; criar, confirmar, cancelar e retomar só com `crm.gerenciar_crm` (auditados).
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from crm.models import DisparoCobranca, ItemDisparo, ModeloAbertura
from crm.services.central_cobranca import disparos

from ..apresentacao_disparos import disparo_detalhe, itens_destinatarios, lista_disparos
from ..base import CrmAPIView
from ..permissoes import ACESSO, GERENCIA
from ..serializers.disparos import (
    DestinatarioSerializer, DestinatariosQuerySerializer, DisparoCriarSerializer, DisparoDetalheSerializer,
    DisparoItemSerializer, DisparosQuerySerializer, ModeloDisparoSerializer,
)
from .cobranca import TAGS_COBRANCA


def _disparos():
    return DisparoCobranca.objects.select_related('modelo', 'versao', 'criado_por', 'confirmado_por', 'cancelado_por')


def _detalhe(pk: int, usuario) -> dict:
    return DisparoDetalheSerializer(disparo_detalhe(get_object_or_404(_disparos(), pk=pk), usuario)).data


class ModelosView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA, summary='Mensagens que podem ser disparadas (ativas e aprovadas pela Meta)',
                   responses=ModeloDisparoSerializer(many=True))
    def get(self, request):
        itens = [{'id': modelo.pk, 'titulo': modelo.titulo, 'texto': versao.corpo,
                  'marcadores': list(versao.mapa_parametros or []), 'nome_meta': versao.nome_meta}
                 for modelo, versao in disparos.modelos_disponiveis()]
        return Response(ModeloDisparoSerializer(itens, many=True).data)


def _publico(dados: dict) -> disparos.Publico:
    return disparos.Publico(atraso_min=dados.get('atraso_min'), atraso_max=dados.get('atraso_max'),
                            vencimento_data=dados.get('vencimento_data'), vencimento_dia=dados.get('vencimento_dia'),
                            parcelas=tuple(dict.fromkeys(dados.get('parcelas') or ())))


class DisparosView(CrmAPIView):
    permissoes = {'GET': ACESSO, 'POST': GERENCIA}

    @extend_schema(tags=TAGS_COBRANCA, summary='Disparos (sem as prévias, a não ser com ?status=PREVIA)',
                   parameters=[DisparosQuerySerializer], responses=DisparoItemSerializer(many=True))
    def get(self, request):
        status = self.validar_query(DisparosQuerySerializer).get('status')
        consulta = _disparos().filter(status=status) if status else _disparos().exclude(
            status=DisparoCobranca.Status.PREVIA)
        return self.paginar_convertendo(consulta, lista_disparos, DisparoItemSerializer)

    @extend_schema(tags=TAGS_COBRANCA, summary='Gerar a prévia de um disparo (nada é enviado até confirmar)',
                   request=DisparoCriarSerializer, responses={201: DisparoDetalheSerializer})
    def post(self, request):
        dados = self.validar(DisparoCriarSerializer)
        modelo = ModeloAbertura.objects.filter(pk=dados['modelo']).first()
        if modelo is None:
            raise ValidationError({'modelo': ['Mensagem não encontrada.']})
        disparo = disparos.montar_previa(modelo, _publico(dados), request.user)
        self.auditar('crm_disparo_previa', objeto=disparo, dados={'filtros': disparo.filtros, 'total': disparo.total})
        return Response(_detalhe(disparo.pk, request.user), status=201)


class DisparoView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA, summary='Disparo: progresso, motivos, estimativa e exemplo do texto',
                   responses=DisparoDetalheSerializer)
    def get(self, request, pk: int):
        return Response(_detalhe(pk, request.user))


class DestinatariosView(CrmAPIView):
    permissoes = {'GET': ACESSO}

    @extend_schema(tags=TAGS_COBRANCA, summary='Destinatários e excluídos do disparo (paginado)',
                   parameters=[DestinatariosQuerySerializer], responses=DestinatarioSerializer(many=True))
    def get(self, request, pk: int):
        from crm.services.relatorios_cobranca import _no_escopo
        from vendas.models import Cliente

        disparo = get_object_or_404(DisparoCobranca, pk=pk)
        situacao = self.validar_query(DestinatariosQuerySerializer).get('situacao')
        visiveis = _no_escopo(Cliente.objects.all(), request.user)
        itens = (ItemDisparo.objects.filter(disparo=disparo, cliente__in=visiveis)
                 .select_related('cliente', 'parcela', 'tentativa__mensagem')
                 .prefetch_related('cliente__telefones_crm').order_by('ordem'))
        if situacao:
            itens = itens.filter(situacao=situacao)
        return self.paginar_convertendo(itens, itens_destinatarios, DestinatarioSerializer)


class _AcaoDisparo(CrmAPIView):
    permissoes = {'POST': GERENCIA}
    acao = ''

    def executar(self, disparo: DisparoCobranca) -> DisparoCobranca:
        raise NotImplementedError

    def post(self, request, pk: int):
        disparo = self.executar(get_object_or_404(DisparoCobranca, pk=pk))
        self.auditar(self.acao, objeto=disparo, dados={'status': disparo.status, 'total': disparo.total})
        return Response(_detalhe(pk, request.user))


@extend_schema(tags=TAGS_COBRANCA, summary='Confirmar a prévia: o disparo entra na fila (AGENDADO)', request=None,
               responses=DisparoDetalheSerializer)
class ConfirmarView(_AcaoDisparo):
    acao = 'crm_disparo_confirmado'

    def executar(self, disparo):
        return disparos.confirmar(disparo, self.request.user)


@extend_schema(tags=TAGS_COBRANCA, summary='Cancelar o disparo (o que já saiu não volta)', request=None,
               responses=DisparoDetalheSerializer)
class CancelarView(_AcaoDisparo):
    acao = 'crm_disparo_cancelado'

    def executar(self, disparo):
        return disparos.cancelar(disparo, self.request.user)


@extend_schema(tags=TAGS_COBRANCA, summary='Retomar um disparo pausado (recusas da Meta ou template)', request=None,
               responses=DisparoDetalheSerializer)
class RetomarDisparoView(_AcaoDisparo):
    acao = 'crm_disparo_retomado'

    def executar(self, disparo):
        return disparos.retomar(disparo)
