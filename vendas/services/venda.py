"""Geração da venda a partir de uma análise de crédito aprovada (fluxo CredFacil)."""
import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from produtos.models import Parcelamento
from vendas.models import Caixa, Pagamento, ProdutoVenda, TipoPagamento, Venda

from .erros import ErroDeNegocio
from .parcelas import calcular_data_primeira_parcela, criar_parcelas

PARCELAS_PAGAS_MINIMAS_POR_VENDA = 3
TIPO_ENTRADA = 'ENTRADA'
TIPO_CREDFACIL = 'IPX'


@dataclass(frozen=True)
class ValoresVenda:
    entrada: Decimal
    valor_credfacil: Decimal
    repasse_logista: Decimal
    parcelas: int
    porcentagem_desconto: Decimal


def _erro_edicao(mensagem: str) -> ErroDeNegocio:
    return ErroDeNegocio(mensagem, corrigir_na_edicao=True)


def validar_vendas_anteriores_do_cpf(cpf: str | None) -> None:
    """Cada venda ativa do mesmo CPF precisa ter ao menos 3 parcelas IPX pagas."""
    cpf_limpo = re.sub(r'\D', '', cpf or '')
    pendentes = (
        Venda.objects.filter(cliente__cpf=cpf_limpo, is_deleted=False)
        .annotate(parcelas_pagas=Count(
            'pagamentos__parcelas_pagamento',
            filter=Q(
                pagamentos__tipo_pagamento__nome__iexact=TIPO_CREDFACIL,
                pagamentos__parcelas_pagamento__pago=True,
            ),
            distinct=True,
        ))
        .filter(parcelas_pagas__lt=PARCELAS_PAGAS_MINIMAS_POR_VENDA)
    )
    if pendentes.exists():
        raise ErroDeNegocio(
            'Para gerar uma nova venda, cada venda anterior do mesmo CPF deve ter '
            'pelo menos 3 parcelas pagas.'
        )


def validar_analise_para_venda(analise, *, bloquear_imei_de_venda_cancelada: bool) -> None:
    """Análise aprovada, com IMEI livre, app instalado (exceto iPhone) e sem venda gerada.

    `bloquear_imei_de_venda_cancelada`: o backoffice considera ocupado o IMEI de
    qualquer venda; a API ignora as vendas canceladas (comportamento herdado).
    """
    if not analise or analise.status != 'A':
        raise ErroDeNegocio('Análise de crédito não aprovada para o cliente.')
    if not analise.imei:
        raise _erro_edicao(
            'Nenhum IMEI associado à análise de crédito. Informe o IMEI antes de gerar a venda.'
        )
    if not getattr(analise.produto, 'is_iphone', False) and analise.status_aplicativo != 'I':
        raise _erro_edicao(
            'Aplicativo não está instalado. Confirme a instalação antes de gerar a venda.'
        )
    if analise.venda:
        raise ErroDeNegocio('Essa solicitação já foi convertida em venda.')

    vendas_com_imei = ProdutoVenda.objects.filter(imei=analise.imei.imei)
    if not bloquear_imei_de_venda_cancelada:
        vendas_com_imei = vendas_com_imei.filter(venda__is_deleted=False)
    if vendas_com_imei.exists():
        raise _erro_edicao(
            f'IMEI {analise.imei.imei} já está sendo usado em outra venda. IMEI deve ser único.'
        )
    if not analise.data_pagamento:
        raise _erro_edicao(
            'Data de pagamento não informada. Informe o dia de pagamento (1, 10 ou 20) '
            'antes de gerar a venda.'
        )
    if not analise.numero_parcelas:
        raise _erro_edicao(
            'Número de parcelas não informado. Informe o número de parcelas antes de gerar a venda.'
        )


def calcular_valores_venda(analise) -> ValoresVenda:
    """Valores da venda pela tabela `Parcelamento` da marca (mesma regra para todo produto)."""
    produto = analise.produto
    parcelas = int(analise.numero_parcelas)
    if not produto.valor:
        raise _erro_edicao('Produto sem valor base cadastrado.')

    entrada = analise.entrada_informada
    if entrada is None:
        entrada = produto.entrada_cliente
    if entrada < produto.entrada_cliente:
        raise _erro_edicao(
            f'Entrada informada (R$ {entrada}) não pode ser menor que a entrada mínima '
            f'do produto (R$ {produto.entrada_cliente}).'
        )

    parcelamento = Parcelamento.objects.filter(marca=produto.marca, qtd_vezes=parcelas).first()
    if not parcelamento:
        marca_nome = produto.marca.nome if produto.marca else 'sem marca'
        raise _erro_edicao(
            f"Nenhum parcelamento cadastrado para {parcelas}x na marca '{marca_nome}'."
        )

    valor_financiado = produto.valor - entrada
    return ValoresVenda(
        entrada=entrada,
        valor_credfacil=valor_financiado + (valor_financiado * parcelamento.porcentagem_juros / 100),
        repasse_logista=produto.valor - entrada,
        parcelas=parcelas,
        porcentagem_desconto=parcelamento.porcentagem_desconto,
    )


def _data_primeira_parcela(analise):
    data = calcular_data_primeira_parcela(analise.data_pagamento)
    if data is None:
        raise _erro_edicao(
            f'Não há vencimento no dia {analise.data_pagamento} dentro de 30 dias. '
            'Escolha outro dia de pagamento.'
        )
    return data


def _criar_pagamentos(venda, analise, valores: ValoresVenda, data_primeira_parcela) -> None:
    loja = analise.loja
    entrada = Pagamento.objects.create(
        loja=loja,
        venda=venda,
        tipo_pagamento=TipoPagamento.objects.get(nome__iexact=TIPO_ENTRADA),
        valor=valores.entrada,
        parcelas=1,
        data_primeira_parcela=timezone.now().date(),
    )
    credfacil = Pagamento.objects.create(
        loja=loja,
        venda=venda,
        tipo_pagamento=TipoPagamento.objects.get(nome__iexact=TIPO_CREDFACIL),
        valor=valores.valor_credfacil,
        parcelas=valores.parcelas,
        data_primeira_parcela=data_primeira_parcela,
        porcentagem_desconto=valores.porcentagem_desconto,
    )
    criar_parcelas(entrada, loja)
    criar_parcelas(credfacil, loja)


def gerar_venda_da_analise(cliente, vendedor, *, bloquear_imei_de_venda_cancelada: bool) -> Venda:
    """Cria Venda, ProdutoVenda e os pagamentos ENTRADA + IPX (com parcelas) da análise.

    Levanta `ErroDeNegocio` sem gravar nada quando alguma regra não é atendida.
    """
    validar_vendas_anteriores_do_cpf(cliente.cpf)
    analise = getattr(cliente, 'analise_credito', None)
    validar_analise_para_venda(
        analise, bloquear_imei_de_venda_cancelada=bloquear_imei_de_venda_cancelada,
    )

    valores = calcular_valores_venda(analise)
    data_primeira_parcela = _data_primeira_parcela(analise)
    with transaction.atomic():
        agora = timezone.now()
        # Caixa aberto é opcional: associa um caixa aberto se houver.
        caixa = Caixa.objects.filter(loja=analise.loja, data_fechamento__isnull=True).first()
        venda = Venda.objects.create(
            loja=analise.loja,
            cliente=cliente,
            vendedor=vendedor,
            caixa=caixa,
            repasse_logista=valores.repasse_logista,
            observacao=analise.observacao,
            criado_por=vendedor,
            modificado_por=vendedor,
            criado_em=agora,
            modificado_em=agora,
        )
        analise.venda = venda
        analise.save()

        ProdutoVenda.objects.create(
            loja=analise.loja,
            venda=venda,
            produto=analise.produto,
            imei=analise.imei.imei,
            valor_unitario=valores.valor_credfacil,
            quantidade=1,
            valor_desconto=0,
        )
        _criar_pagamentos(venda, analise, valores, data_primeira_parcela)
    return venda
