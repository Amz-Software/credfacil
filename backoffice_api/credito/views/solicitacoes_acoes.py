"""Ações POST sobre a solicitação: decisões, observações, app, iCloud, IMEI, venda e Serasa.

Toda regra vem de `vendas/services/analise.py` e `vendas/services/venda.py`; as
notificações e o WebSocket saem dos signals de `AnaliseCreditoCliente` (não
são repetidos aqui). Cada ação grava `RegistroAuditoria` na mesma transação.
"""
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from vendas.models import Loja, ObservacaoSolicitacao
from vendas.services import ErroDeNegocio
from vendas.services import analise as servico_analise
from vendas.services.venda import gerar_venda_da_analise

from ..regras import ROTULOS_STATUS, STATUS_APROVADO, STATUS_CANCELADO, STATUS_REPROVADO
from ..serializers.entradas import (
    CreditoImeiEntradaSerializer,
    CreditoLogSerasaEntradaSerializer,
    CreditoMotivoSerializer,
    CreditoObservacaoEntradaSerializer,
    CreditoStatusAppEntradaSerializer,
)
from ..serializers.estruturas import CreditoObservacaoSerializer
from ..serializers.respostas import (
    CreditoAcaoRespostaSerializer,
    CreditoGerarVendaRespostaSerializer,
    CreditoLogSerasaRespostaSerializer,
)
from ..serializers.solicitacao_lista import CreditoSolicitacaoListaSerializer

PREFIXO_OBSERVACAO = {STATUS_REPROVADO: 'Motivo da reprovação', STATUS_CANCELADO: 'Motivo do cancelamento'}


def _validar(serializer_class, dados) -> dict:
    serializer = serializer_class(data=dados)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _cancelar_sem_desfazer_venda(analise, usuario):
    # Mesmo comportamento da tela Django: só muda o status (a venda gerada continua).
    return servico_analise.cancelar_analise(analise, usuario, desfazer_venda=False)


class AcoesDaSolicitacaoMixin:
    """Ações do analista; usa `get_object()` (escopo de loja → 404) e `auditar()` da view."""

    def _resposta(self, cliente_id: int, mensagem: str, codigo: int = status.HTTP_200_OK, **extra) -> Response:
        cliente = self.get_queryset().get(pk=cliente_id)
        solicitacao = CreditoSolicitacaoListaSerializer(cliente, context=self.get_serializer_context()).data
        return Response({'mensagem': mensagem, 'solicitacao': solicitacao, **extra}, status=codigo)

    def _auditar_analise(self, acao: str, cliente, *, motivo: str = '', **dados):
        return self.auditar(
            acao, objeto=cliente.analise_credito, motivo=motivo, dados={'solicitacao_id': cliente.pk, **dados},
        )

    def _mudar_status(self, request, *, destino: str, transicao, acao: str, mensagem: str, exige_motivo: bool):
        motivo = _validar(CreditoMotivoSerializer, request.data)['motivo'] if exige_motivo else ''
        cliente = self.get_object()
        analise = cliente.analise_credito
        if analise.status == destino:
            raise ErroDeNegocio(f'A solicitação já está com o status "{ROTULOS_STATUS[destino]}".')
        anterior = analise.status
        with transaction.atomic():
            transicao(analise, request.user)
            if motivo:
                ObservacaoSolicitacao.objects.create(
                    analise_credito=analise, autor=request.user, texto=f'{PREFIXO_OBSERVACAO[destino]}: {motivo}',
                )
            self._auditar_analise(acao, cliente, motivo=motivo, status_anterior=anterior, status_novo=analise.status)
        return self._resposta(cliente.pk, mensagem)

    @extend_schema(request=None, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'])
    def aprovar(self, request, pk=None):
        return self._mudar_status(
            request, destino=STATUS_APROVADO, transicao=servico_analise.aprovar_analise,
            acao='analise_aprovada', mensagem='Análise de crédito aprovada.', exige_motivo=False,
        )

    @extend_schema(request=CreditoMotivoSerializer, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'])
    def reprovar(self, request, pk=None):
        return self._mudar_status(
            request, destino=STATUS_REPROVADO, transicao=servico_analise.reprovar_analise,
            acao='analise_reprovada', mensagem='Análise de crédito reprovada.', exige_motivo=True,
        )

    @extend_schema(request=CreditoMotivoSerializer, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'])
    def cancelar(self, request, pk=None):
        return self._mudar_status(
            request, destino=STATUS_CANCELADO, transicao=_cancelar_sem_desfazer_venda,
            acao='analise_cancelada', mensagem='Análise de crédito cancelada.', exige_motivo=True,
        )

    @extend_schema(request=CreditoObservacaoEntradaSerializer, responses={201: CreditoObservacaoSerializer})
    @action(detail=True, methods=['post'])
    def observacoes(self, request, pk=None):
        texto = _validar(CreditoObservacaoEntradaSerializer, request.data)['texto']
        cliente = self.get_object()
        with transaction.atomic():
            observacao = ObservacaoSolicitacao.objects.create(
                analise_credito=cliente.analise_credito, autor=request.user, texto=texto,
            )
            self._auditar_analise('observacao_adicionada', cliente, observacao_id=observacao.pk)
        return Response(CreditoObservacaoSerializer(observacao).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CreditoStatusAppEntradaSerializer, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'], url_path='status-app')
    def status_app(self, request, pk=None):
        novo = _validar(CreditoStatusAppEntradaSerializer, request.data)['status_app']
        cliente = self.get_object()
        analise = cliente.analise_credito
        anterior = analise.status_aplicativo
        with transaction.atomic():
            servico_analise.atualizar_status_aplicativo(analise, novo)
            self._auditar_analise('status_app_alterado', cliente, status_app_anterior=anterior, status_app_novo=novo)
        return self._resposta(
            cliente.pk, f'Status do aplicativo atualizado para {analise.get_status_aplicativo_display()}.',
        )

    @extend_schema(request=None, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'], url_path='instalar-app')
    def instalar_app(self, request, pk=None):
        cliente = self.get_object()
        with transaction.atomic():
            servico_analise.marcar_instalacao_pendente(cliente.analise_credito)
            self._auditar_analise('instalacao_app_marcada', cliente)
        return self._resposta(cliente.pk, 'Status alterado para Confirmação pendente.')

    @extend_schema(request=None, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'], url_path='confirmar-instalacao')
    def confirmar_instalacao(self, request, pk=None):
        cliente = self.get_object()
        with transaction.atomic():
            servico_analise.confirmar_instalacao_analista(cliente.analise_credito, request.user)
            self._auditar_analise('instalacao_app_confirmada', cliente)
        return self._resposta(cliente.pk, 'Instalação confirmada pelo analista. Venda liberada para geração.')

    @extend_schema(request=None, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'], url_path='confirmar-icloud')
    def confirmar_icloud(self, request, pk=None):
        cliente = self.get_object()
        with transaction.atomic():
            servico_analise.confirmar_icloud_analista(cliente.analise_credito, request.user)
            self._auditar_analise('icloud_confirmado', cliente)
        return self._resposta(cliente.pk, f'Configuração iCloud confirmada para {cliente.nome}.')

    @extend_schema(request=CreditoImeiEntradaSerializer, responses=CreditoAcaoRespostaSerializer)
    @action(detail=True, methods=['post'], url_path='informar-imei')
    def informar_imei(self, request, pk=None):
        imei = _validar(CreditoImeiEntradaSerializer, request.data)['imei']
        cliente = self.get_object()
        analise = cliente.analise_credito
        with transaction.atomic():
            _, criado = servico_analise.informar_imei(analise, request.user, imei, analise.loja or cliente.loja)
            self._auditar_analise('imei_informado', cliente, imei=imei, imei_criado_no_estoque=criado)
        acao = 'cadastrado e associado' if criado else 'associado'
        return self._resposta(cliente.pk, f'IMEI {imei} {acao} à análise. Venda liberada para geração.')

    @extend_schema(request=None, responses={201: CreditoGerarVendaRespostaSerializer})
    @action(detail=True, methods=['post'], url_path='gerar-venda')
    def gerar_venda(self, request, pk=None):
        cliente = self.get_object()
        if not Loja.objects.filter(credfacil=True).exists():
            raise ErroDeNegocio('Loja CredFacil não encontrada.')
        with transaction.atomic():
            # Mesmo cálculo e as mesmas travas da tela Django (IMEI de venda cancelada continua ocupado).
            venda = gerar_venda_da_analise(cliente, request.user, bloquear_imei_de_venda_cancelada=True)
            self.auditar(
                'venda_gerada', objeto=venda,
                dados={'solicitacao_id': cliente.pk, 'analise_id': cliente.analise_credito.pk},
            )
        return self._resposta(
            cliente.pk, f'Venda criada para o cliente {cliente.nome}.', status.HTTP_201_CREATED, venda_id=venda.pk,
        )

    @extend_schema(request=CreditoLogSerasaEntradaSerializer, responses={201: CreditoLogSerasaRespostaSerializer})
    @action(detail=True, methods=['post'], url_path='log-consulta-serasa')
    def log_consulta_serasa(self, request, pk=None):
        tipo = _validar(CreditoLogSerasaEntradaSerializer, request.data)['tipo']
        cliente = self.get_object()
        with transaction.atomic():
            acesso = self._registrar_acesso_serasa(cliente, tipo)
            self._auditar_analise('consulta_serasa_aberta', cliente, tipo=tipo)
        return Response(CreditoLogSerasaRespostaSerializer(acesso).data, status=status.HTTP_201_CREATED)
