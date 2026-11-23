"""Parcelas (editar e adicionar) e comprovantes de pagamento (enviar, baixar, excluir)."""
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from vendas.models import ComprovanteParcela, Parcela

from ...nucleo.erros import NAO_ENCONTRADO_RECURSO, ErroBackoffice
from ...nucleo.permissoes import EmGrupo, PermissaoNegada
from ..base import ContasAReceberBaseView
from ..constantes import GRUPOS_ANALISTA_ADMIN
from ..entradas import AdicionarParcelasSerializer, ComprovanteEntradaSerializer, ParcelaEdicaoSerializer
from ..serializers import ComprovanteSerializer, ContaAReceberDetalheSerializer, ParcelaSerializer
from ..servicos import adicionar_parcelas, editar_parcela
from .contas import DetalheMixin

TAGS = ['bo-financeiro']
ANALISTA_OU_ADMIN = EmGrupo(*GRUPOS_ANALISTA_ADMIN)
PERMISSAO_VENCIMENTO = 'vendas.change_vencimento_parcela'
MENSAGEM_SEM_PERMISSAO_VENCIMENTO = 'Você não tem permissão para alterar a data de vencimento das parcelas.'


def _json(valor):
    return valor.isoformat() if hasattr(valor, 'isoformat') else (str(valor) if valor is not None else None)


@extend_schema(tags=TAGS)
class AdicionarParcelasView(DetalheMixin, ContasAReceberBaseView):
    """Inclui até 4 parcelas e redistribui o saldo entre as pendentes."""

    permissoes = {'POST': [ANALISTA_OU_ADMIN, 'vendas.add_parcela']}

    @extend_schema(request=AdicionarParcelasSerializer, responses={201: ContaAReceberDetalheSerializer})
    def post(self, request, pk: int):
        pagamento = self.obter_pagamento(pk)
        entrada = AdicionarParcelasSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        pedidos = [item.get('data_vencimento') for item in entrada.validated_data['parcelas']]
        resultado = adicionar_parcelas(pagamento, pedidos, request.user)
        self.auditar('parcelas_adicionadas', objeto=pagamento,
                     motivo=entrada.validated_data.get('motivo', ''), dados=resultado)
        return self.resposta_detalhe(pk, status=201)


def _parcela_para_resposta(pk: int) -> Parcela:
    comprovantes = ComprovanteParcela.objects.select_related('criado_por').order_by('-criado_em', '-id')
    return (
        Parcela.objects.select_related('modificado_por')
        .prefetch_related(Prefetch('comprovantes', queryset=comprovantes))
        .get(pk=pk)
    )


@extend_schema(tags=TAGS)
class ParcelaView(ContasAReceberBaseView):
    """Edita pagamento e vencimento de uma parcela (o vencimento exige permissão própria)."""

    permissoes = {'PATCH': [ANALISTA_OU_ADMIN, 'vendas.change_pagamento']}

    @extend_schema(request=ParcelaEdicaoSerializer, responses=ParcelaSerializer)
    def patch(self, request, pk: int):
        parcela = self.obter_parcela(pk)
        entrada = ParcelaEdicaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = dict(entrada.validated_data)
        motivo = dados.pop('motivo', '')
        novo_vencimento = dados.get('data_vencimento')
        if novo_vencimento is not None and novo_vencimento != parcela.data_vencimento \
                and not request.user.has_perm(PERMISSAO_VENCIMENTO):
            raise PermissaoNegada(MENSAGEM_SEM_PERMISSAO_VENCIMENTO)
        mudancas = editar_parcela(parcela, dados, request.user)
        if mudancas:
            self.auditar(
                'parcela_editada', objeto=parcela, motivo=motivo,
                dados={
                    'pagamento_id': parcela.pagamento_id,
                    'numero_parcela': parcela.numero_parcela,
                    'alteracoes': {c: {'antes': _json(m.antes), 'depois': _json(m.depois)} for c, m in mudancas.items()},
                },
            )
        return Response(ParcelaSerializer(_parcela_para_resposta(parcela.pk), context={'request': request}).data)


@extend_schema(tags=TAGS)
class ComprovanteUploadView(ContasAReceberBaseView):
    permissoes = {'POST': [ANALISTA_OU_ADMIN, 'vendas.change_pagamento']}
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request={'multipart/form-data': ComprovanteEntradaSerializer},
                   responses={201: ComprovanteSerializer})
    def post(self, request, pk: int):
        parcela = self.obter_parcela(pk)
        entrada = ComprovanteEntradaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        comprovante = ComprovanteParcela(
            parcela=parcela,
            loja=parcela.pagamento.loja,
            arquivo=entrada.validated_data['arquivo'],
            observacao=entrada.validated_data.get('observacao', ''),
        )
        comprovante.save(user=request.user)
        self.auditar(
            'comprovante_anexado', objeto=comprovante,
            dados={'parcela_id': parcela.pk, 'pagamento_id': parcela.pagamento_id, 'arquivo': comprovante.nome_arquivo},
        )
        return Response(ComprovanteSerializer(comprovante).data, status=201)


@extend_schema(tags=TAGS)
class ComprovanteArquivoView(ContasAReceberBaseView):
    """Entrega o arquivo depois de conferir permissão e escopo; o acesso é auditado."""

    permissoes = {'GET': [ANALISTA_OU_ADMIN, 'vendas.view_pagamento']}

    @extend_schema(
        parameters=[OpenApiParameter('download', OpenApiTypes.BOOL, description='1 força o download')],
        responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY},
    )
    def get(self, request, pk: int):
        comprovante = self.obter_comprovante(pk)
        try:
            arquivo = comprovante.arquivo.open('rb')
        except (ValueError, FileNotFoundError, OSError):
            raise ErroBackoffice(
                'Arquivo do comprovante não encontrado no servidor.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404,
            )
        self.auditar('comprovante_acessado', objeto=comprovante,
                     dados={'parcela_id': comprovante.parcela_id, 'arquivo': comprovante.nome_arquivo})
        resposta = FileResponse(
            arquivo, as_attachment=request.query_params.get('download') == '1', filename=comprovante.nome_arquivo,
        )
        resposta['Cache-Control'] = 'private, no-store'
        resposta['X-Content-Type-Options'] = 'nosniff'
        return resposta


@extend_schema(tags=TAGS)
class ComprovanteView(ContasAReceberBaseView):
    permissoes = {'DELETE': [ANALISTA_OU_ADMIN, 'vendas.change_pagamento']}

    @extend_schema(responses={204: None})
    def delete(self, request, pk: int):
        comprovante = self.obter_comprovante(pk)
        dados = {'parcela_id': comprovante.parcela_id, 'pagamento_id': comprovante.parcela.pagamento_id,
                 'arquivo': comprovante.nome_arquivo}
        with transaction.atomic():
            self.auditar('comprovante_removido', objeto=comprovante, dados=dados)
            comprovante.delete()
        return Response(status=204)
