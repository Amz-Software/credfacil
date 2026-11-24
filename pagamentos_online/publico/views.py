"""API do app do cliente (`/api/publico/v1/`), sem login: acesso pelo CPF + nascimento ou pelo token do pagamento.

Erros no formato {"erro": {"codigo", "mensagem"}}. Escritas limitadas pelo escopo `publico`.
"""
import hashlib
import logging
import os
import re

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle
from rest_framework.views import APIView

from vendas.models import ComprovanteParcela, Pagamento, Parcela
from vendas.services.erros import ErroDeNegocio

from ..models import Cobranca
from ..servicos.cobrancas import gerar_cobranca
from ..servicos.comprovante import gerar_pdf, nome_do_arquivo
from . import dados

logger = logging.getLogger(__name__)

MAX_PAGAMENTOS_CONSULTA = 20
MAX_CONSULTAS_POR_CPF = 10
JANELA_CONSULTAS_CPF = 60 * 60  # 1 hora
MAX_COMPROVANTES_DO_CLIENTE = 3


def tentativas_do_cpf_esgotadas(cpf: str) -> bool:
    """Limite por CPF (além do por IP): adivinhar a data de nascimento exige muitas tentativas no mesmo CPF."""
    cache = caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')]
    chave = f'pagamentos_online:consulta:{hashlib.sha256(cpf.encode()).hexdigest()}'
    cache.add(chave, 0, timeout=JANELA_CONSULTAS_CPF)
    try:
        tentativas = cache.incr(chave)
    except ValueError:  # a chave expirou entre o add e o incr
        cache.set(chave, 1, timeout=JANELA_CONSULTAS_CPF)
        tentativas = 1
    return tentativas > MAX_CONSULTAS_POR_CPF


def _erro(mensagem: str, codigo: str = 'regra_de_negocio', status_http: int = 400) -> Response:
    return Response({'erro': {'codigo': codigo, 'mensagem': mensagem}}, status=status_http)


class PublicoView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    throttle_scope = 'publico'

    def get_throttles(self):
        if self.request.method == 'GET':
            return [AnonRateThrottle()]
        return [ScopedRateThrottle()]

    def handle_exception(self, exc):
        if isinstance(exc, ErroDeNegocio):
            return _erro(exc.mensagem, status_http=exc.status_http)
        resposta = super().handle_exception(exc)
        if resposta is not None and resposta.status_code == status.HTTP_404_NOT_FOUND:
            return _erro('Não encontrado.', 'nao_encontrado', 404)
        if resposta is not None and resposta.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            return _erro('Muitas tentativas. Aguarde um minuto e tente de novo.', 'limite_excedido', 429)
        return resposta

    def pagamento(self, token) -> Pagamento:
        return get_object_or_404(
            Pagamento.objects.select_related('venda__cliente'), token_publico=token, venda__is_deleted=False,
        )

    def parcela(self, token, pk: int) -> Parcela:
        pagamento = self.pagamento(token)
        return get_object_or_404(Parcela.objects.select_related('pagamento__venda__cliente'), pk=pk, pagamento=pagamento)


class ConsultaEntrada(serializers.Serializer):
    cpf = serializers.CharField(max_length=14)
    data_nascimento = serializers.DateField(input_formats=['%Y-%m-%d', '%d/%m/%Y'])

    def validate_cpf(self, valor: str) -> str:
        digitos = re.sub(r'\D', '', valor)
        if len(digitos) != 11:
            raise serializers.ValidationError('Informe um CPF com 11 números.')
        return digitos


class ConsultaView(PublicoView):
    """CPF + data de nascimento → compras do cliente (cada uma com o token para abrir os detalhes)."""

    def post(self, request):
        entrada = ConsultaEntrada(data=request.data)
        if not entrada.is_valid():
            return _erro('Confira o CPF e a data de nascimento.', 'validacao')
        if tentativas_do_cpf_esgotadas(entrada.validated_data['cpf']):
            return _erro('Muitas tentativas para este CPF. Tente de novo mais tarde.', 'limite_excedido', 429)
        pagamentos = (Pagamento.objects
                      .filter(venda__cliente__cpf=entrada.validated_data['cpf'],
                              venda__cliente__nascimento=entrada.validated_data['data_nascimento'],
                              venda__is_deleted=False, tipo_pagamento__parcelas=True)
                      .select_related('venda').prefetch_related('parcelas_pagamento')
                      .order_by('-venda__data_venda')[:MAX_PAGAMENTOS_CONSULTA])
        return Response({'pagamentos': [dados.resumo_para_consulta(p) for p in pagamentos]})


class PagamentoView(PublicoView):
    def get(self, request, token):
        return Response(dados.detalhe_do_pagamento(self.pagamento(token)))


class OpcoesView(PublicoView):
    def get(self, request, token, pk: int):
        return Response({'opcoes': dados.opcoes(self.parcela(token, pk))})


class CobrancaEntrada(serializers.Serializer):
    forma = serializers.ChoiceField(choices=Cobranca.Forma.choices)


class CriarCobrancaView(PublicoView):
    def post(self, request, token, pk: int):
        parcela = self.parcela(token, pk)
        entrada = CobrancaEntrada(data=request.data)
        if not entrada.is_valid():
            return _erro('Escolha uma forma de pagamento válida.', 'validacao')
        cobranca = gerar_cobranca(parcela, entrada.validated_data['forma'], Cobranca.Origem.CLIENTE)
        return Response(dados.cobranca(cobranca), status=status.HTTP_201_CREATED)


class CobrancaView(PublicoView):
    """Situação de uma cobrança (o app consulta enquanto o cliente paga)."""

    def get(self, request, token, referencia):
        pagamento = self.pagamento(token)
        cobranca = get_object_or_404(Cobranca, referencia=referencia, parcela__pagamento=pagamento)
        return Response(dados.cobranca(cobranca))


class ComprovanteView(PublicoView):
    def get(self, request, token, referencia):
        pagamento = self.pagamento(token)
        cobranca = get_object_or_404(
            Cobranca.objects.select_related('parcela__pagamento__venda__cliente'),
            referencia=referencia, parcela__pagamento=pagamento, status=Cobranca.Status.PAGA,
        )
        nome = f'comprovante-parcela-{cobranca.parcela.numero_parcela}.pdf'
        anexado = cobranca.parcela.comprovantes.filter(arquivo__endswith=nome_do_arquivo(cobranca)).first()
        if anexado:  # o PDF já gerado na baixa: sem custo de gerar de novo a cada acesso
            resposta = FileResponse(anexado.arquivo.open('rb'), content_type='application/pdf', filename=nome)
        else:
            resposta = HttpResponse(gerar_pdf(cobranca), content_type='application/pdf')
        resposta['Content-Disposition'] = f'inline; filename="{nome}"'
        resposta['Cache-Control'] = 'private, no-store'
        return resposta


MENSAGEM_ARQUIVO = 'Envie o comprovante em PDF ou imagem (JPG, PNG, WEBP ou HEIC).'
MARCAS_HEIC = (b'ftypheic', b'ftypheix', b'ftypmif1', b'ftypmsf1', b'ftyphevc')


def _conteudo_confere(arquivo, extensao: str) -> bool:
    """Confere o conteúdo, não só a extensão: PDF começa com %PDF-, imagem precisa abrir no Pillow."""
    inicio = arquivo.read(16)
    arquivo.seek(0)
    if extensao == 'pdf':
        return inicio.startswith(b'%PDF-')
    if extensao == 'heic':
        return inicio[4:12] in MARCAS_HEIC
    try:
        from PIL import Image

        with Image.open(arquivo) as imagem:
            imagem.verify()
        return True
    except Exception:  # noqa: BLE001 — qualquer falha do Pillow = não é imagem válida
        return False
    finally:
        arquivo.seek(0)


def _validar_arquivo(arquivo) -> None:
    extensao = os.path.splitext(arquivo.name or '')[1].lstrip('.').lower()
    if extensao not in ComprovanteParcela.EXTENSOES_PERMITIDAS:
        raise ErroDeNegocio(MENSAGEM_ARQUIVO)
    if arquivo.size > ComprovanteParcela.TAMANHO_MAXIMO_BYTES:
        raise ErroDeNegocio('O comprovante passa de 10 MB.')
    if not _conteudo_confere(arquivo, extensao):
        raise ErroDeNegocio(f'Não conseguimos ler o arquivo. {MENSAGEM_ARQUIVO}')


def _pode_informar(parcela: Parcela) -> None:
    pagamento = parcela.pagamento
    if parcela.pago:
        raise ErroDeNegocio('Essa parcela já está paga.')
    if pagamento.quitado or pagamento.desativado or pagamento.devolucao:
        raise ErroDeNegocio('Essa compra está encerrada. Fale com a nossa equipe.')
    enviados = parcela.comprovantes.filter(observacao=OBSERVACAO_CLIENTE).count()
    if enviados >= MAX_COMPROVANTES_DO_CLIENTE:
        raise ErroDeNegocio('Você já enviou comprovantes desta parcela. A equipe vai conferir.')


OBSERVACAO_CLIENTE = 'Enviado pelo cliente no app de pagamentos'


class InformarPagamentoView(PublicoView):
    """O cliente avisa que pagou (Pix da chave da empresa, transferência...); a equipe confere."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, token, pk: int):
        arquivo = request.FILES.get('comprovante')
        if arquivo:
            _validar_arquivo(arquivo)
        with transaction.atomic():
            parcela = (Parcela.objects.select_for_update().select_related('pagamento')
                       .get(pk=self.parcela(token, pk).pk))
            _pode_informar(parcela)
            agora = timezone.now()
            parcela.pagamento_efetuado = True
            parcela.pagamento_efetuado_em = agora
            parcela.data_pagamento = timezone.localdate(agora)
            parcela.save(update_fields=['pagamento_efetuado', 'pagamento_efetuado_em', 'data_pagamento',
                                        'modificado_em'])
            if arquivo:
                ComprovanteParcela.objects.create(
                    parcela=parcela, loja=parcela.pagamento.loja, arquivo=arquivo, observacao=OBSERVACAO_CLIENTE,
                )
        return Response(dados.detalhe_do_pagamento(parcela.pagamento))


class InformarQuitacaoView(PublicoView):
    """Quitação com desconto paga no Pix da empresa: todas as parcelas em aberto ficam em confirmação."""

    def post(self, request, token):
        pagamento = self.pagamento(token)
        atualizadas = (pagamento.parcelas_pagamento.filter(pagamento_efetuado=False, pago=False)
                       .update(pagamento_efetuado=True, pagamento_efetuado_em=timezone.now()))
        if not atualizadas:
            raise ErroDeNegocio('Nenhuma parcela nova para informar.')
        return Response(dados.detalhe_do_pagamento(pagamento))
