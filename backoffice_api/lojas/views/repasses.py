"""Repasses ao logista: lista geral, criação, edição/status e agenda por loja."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.response import Response

from financeiro.models import Repasse

from ...nucleo.erros import VALIDACAO, ErroBackoffice
from ..base import TAGS, LojasBaseView
from ..serializers_repasses import (
    AgendaDaLojaSerializer,
    RepasseCriacaoSerializer,
    RepasseEdicaoSerializer,
    RepasseSerializer,
)
from ..servicos import (
    STATUS_REPASSE,
    calendario_por_loja,
    data_do_repasse,
    validar_edicao_de_valores,
    validar_mudanca_de_status,
)
from .lojas import ler_periodo

ORDENACAO = {'data': 'data', 'valor': 'valor', 'status': 'status', 'criado_em': 'criado_em'}
MESES_AGENDA_PADRAO = 1


def _erro(campo: str, mensagem: str) -> ErroBackoffice:
    return ErroBackoffice('Revise os filtros informados.', codigo=VALIDACAO, campos={campo: [mensagem]})


def _inteiro(valor: str, campo: str) -> int:
    if not valor.isdigit() or len(valor) > 10:
        raise _erro(campo, 'Informe um número inteiro.')
    return int(valor)


def _retrato(repasse: Repasse) -> dict:
    return {'valor': str(repasse.valor), 'data': timezone.localtime(repasse.data).date().isoformat(),
            'status': repasse.status, 'observacao': repasse.observacao or ''}


class RepassesBaseView(LojasBaseView):
    def repasses(self):
        return self.filtrar_por_lojas(Repasse.objects.select_related('loja', 'criado_por', 'atualizado_por'), 'loja')


@extend_schema(tags=TAGS)
class RepassesView(RepassesBaseView):
    permissoes = {'GET': ['financeiro.view_repasse'], 'POST': ['financeiro.add_repasse']}

    @extend_schema(
        parameters=[
            OpenApiParameter('loja', int), OpenApiParameter('status', str, enum=list(STATUS_REPASSE)),
            OpenApiParameter('data_inicio', OpenApiTypes.DATE), OpenApiParameter('data_fim', OpenApiTypes.DATE),
            OpenApiParameter('ordenar', str, description='data, valor, status, criado_em (com - para desc.)'),
        ],
        responses=RepasseSerializer(many=True),
    )
    def get(self, request):
        params = request.query_params
        repasses = self.repasses()
        if params.get('loja'):
            loja = self.obter_loja(_inteiro(params['loja'], 'loja'))
            repasses = repasses.filter(loja=loja)
        if params.get('status'):
            if params['status'] not in STATUS_REPASSE:
                raise _erro('status', f'Use um destes valores: {", ".join(STATUS_REPASSE)}.')
            repasses = repasses.filter(status=params['status'])
        data_inicio, data_fim = ler_periodo(params)
        if data_inicio:
            repasses = repasses.filter(data__date__gte=data_inicio)
        if data_fim:
            repasses = repasses.filter(data__date__lte=data_fim)
        ordenar = (params.get('ordenar') or '-data').strip()
        if ordenar.lstrip('-') not in ORDENACAO:
            raise _erro('ordenar', f'Use um destes campos: {", ".join(ORDENACAO)}.')
        return self.paginar(repasses.order_by(ordenar, '-id'), RepasseSerializer)

    @extend_schema(request=RepasseCriacaoSerializer, responses={201: RepasseSerializer})
    def post(self, request):
        entrada = RepasseCriacaoSerializer(data=request.data, lojas=self.lojas_visiveis())
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        repasse = Repasse.objects.create(
            loja=dados['loja'], valor=dados['valor'], data=data_do_repasse(dados['data']),
            status=dados['status'], observacao=dados['observacao'],
            criado_por=request.user, atualizado_por=request.user,
        )
        self.auditar('repasse_criado', objeto=repasse, dados={'loja_id': repasse.loja_id, **_retrato(repasse)})
        return Response(RepasseSerializer(repasse).data, status=201)


@extend_schema(tags=TAGS)
class RepasseView(RepassesBaseView):
    permissoes = {'PATCH': ['financeiro.change_repasse']}

    @extend_schema(request=RepasseEdicaoSerializer, responses=RepasseSerializer)
    def patch(self, request, pk: int):
        repasse = get_object_or_404(self.repasses(), pk=pk)
        entrada = RepasseEdicaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = dict(entrada.validated_data)
        motivo = dados.pop('motivo', '')
        antes = _retrato(repasse)
        if 'data' in dados:
            dados['data'] = data_do_repasse(dados['data'])
        alterados = {campo: valor for campo, valor in dados.items() if getattr(repasse, campo) != valor}
        validar_edicao_de_valores(repasse, alterados)
        validar_mudanca_de_status(repasse, alterados.get('status'))
        if not alterados:
            return Response(RepasseSerializer(repasse).data)
        with transaction.atomic():
            for campo, valor in alterados.items():
                setattr(repasse, campo, valor)
            repasse.atualizado_por = request.user
            repasse.save()
            depois = _retrato(repasse)
            if 'status' in alterados:
                self.auditar('repasse_status_alterado', objeto=repasse, motivo=motivo,
                             dados={'antes': antes['status'], 'depois': depois['status']})
            outros = {c: {'antes': antes[c], 'depois': depois[c]} for c in alterados if c != 'status'}
            if outros:
                self.auditar('repasse_alterado', objeto=repasse, motivo=motivo, dados=outros)
        return Response(RepasseSerializer(repasse).data)


@extend_schema(tags=TAGS)
class RepassesAgendadosView(RepassesBaseView):
    """Próximos repasses e atrasados de cada loja do escopo (calendário 6/16/26)."""

    permissoes = {'GET': ['financeiro.view_repasse']}

    @extend_schema(
        parameters=[OpenApiParameter('loja', int),
                    OpenApiParameter('meses_atras', int, description='0 a 6 (padrão 1)')],
        responses=AgendaDaLojaSerializer(many=True),
    )
    def get(self, request):
        params = request.query_params
        lojas = self.lojas_visiveis()
        if params.get('loja'):
            lojas = lojas.filter(pk=self.obter_loja(_inteiro(params['loja'], 'loja')).pk)
        meses = _inteiro(params['meses_atras'], 'meses_atras') if params.get('meses_atras') else MESES_AGENDA_PADRAO
        paginador = self.pagination_class()
        pagina = paginador.paginate_queryset(lojas.order_by('nome', 'id'), request, view=self)
        calendario = calendario_por_loja(pagina, meses_atras=meses)
        agenda = []
        for loja in pagina:
            periodos, atrasados = calendario[loja.pk]
            agenda.append({
                'loja': loja,
                'atrasados': [p for p in periodos if p['atrasado']],
                'proximos': [p for p in periodos if not p['feito'] and not p['atrasado']],
                'total_atrasados': atrasados,
            })
        return paginador.get_paginated_response(AgendaDaLojaSerializer(agenda, many=True).data)
