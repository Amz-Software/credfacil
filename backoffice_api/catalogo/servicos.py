"""Regras do catálogo usadas pela API: visibilidade por loja e simulação de parcelas.

A visibilidade reaproveita `Loja.produtos_permitidos_qs` (a mesma da tela Django e da
API atual) e a simulação reaproveita `vendas.services.venda.calcular_valores_venda`
(a mesma conta da geração da venda), sem duplicar regra.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Exists, OuterRef, Q, QuerySet

from produtos.models import Marca, Parcelamento, Produto
from vendas.models import Loja
from vendas.services.erros import ErroDeNegocio
from vendas.services.venda import calcular_valores_venda

PERMISSAO_VER_TODOS_PRODUTOS = 'produtos.view_all_produtos'
CENTAVOS = Decimal('0.01')


def marcas_visiveis(lojas: QuerySet | None) -> QuerySet:
    """Marcas sem lojas permitidas (visíveis para todas) ou liberadas para alguma das `lojas`.

    `lojas=None`: sem restrição (acesso global sem loja escolhida).
    """
    marcas = Marca.objects.all()
    if lojas is None:
        return marcas
    vinculos = Marca.lojas_permitidas.through.objects.filter(marca_id=OuterRef('pk'))
    liberada = vinculos.filter(loja_id__in=lojas.values('pk'))
    return marcas.filter(~Exists(vinculos) | Exists(liberada))


def produtos_visiveis(user, lojas: QuerySet | None) -> QuerySet:
    """Produtos que o usuário pode ver (regra da tela de produtos).

    - `view_all_produtos`: todos, ativos e inativos;
    - demais: só os ativos permitidos para alguma das lojas (`Loja.produtos_permitidos_qs`:
      iPhone, produtos bloqueados e lojas permitidas da marca);
    - sem loja nenhuma: ativos cuja marca não restringe lojas (como a API atual).
    """
    if user.has_perm(PERMISSAO_VER_TODOS_PRODUTOS):
        return Produto.objects.all()
    lojas_consulta = list(Loja.objects.all() if lojas is None else lojas)
    if not lojas_consulta:
        return Produto.objects.filter(ativo=True).filter(
            Q(marca__isnull=True) | Q(marca__lojas_permitidas__isnull=True)
        ).distinct()
    ids: set[int] = set()
    for loja in lojas_consulta:
        ids.update(loja.produtos_permitidos_qs().values_list('pk', flat=True))
    return Produto.objects.filter(pk__in=ids)


def _opcao(parcelamento: Parcelamento, produto: Produto, entrada: Decimal | None) -> dict:
    analise = SimpleNamespace(
        produto=produto, numero_parcelas=parcelamento.qtd_vezes, entrada_informada=entrada
    )
    valores = calcular_valores_venda(analise)
    return {
        'qtd_vezes': valores.parcelas,
        'porcentagem_juros': parcelamento.porcentagem_juros,
        'porcentagem_desconto': valores.porcentagem_desconto,
        'valor_financiado': (produto.valor - valores.entrada).quantize(CENTAVOS),
        'valor_total': valores.valor_credfacil.quantize(CENTAVOS),
        'valor_parcela': (valores.valor_credfacil / valores.parcelas).quantize(CENTAVOS),
    }


def simular_parcelas(produto: Produto, entrada: Decimal | None = None) -> dict:
    """Opções de parcelamento do produto (tabela `Parcelamento` da marca).

    `entrada=None` usa a entrada mínima do produto. Levanta `ErroDeNegocio` se o
    produto não tiver valor base ou se a entrada for menor que a mínima.
    """
    if not produto.valor:
        raise ErroDeNegocio('Produto sem valor base cadastrado.')
    parcelamentos = Parcelamento.objects.filter(marca=produto.marca, qtd_vezes__gt=0).order_by('qtd_vezes')
    opcoes = [_opcao(parcelamento, produto, entrada) for parcelamento in parcelamentos]
    aviso = None
    if not opcoes:
        marca = produto.marca.nome if produto.marca else 'sem marca'
        aviso = f"Nenhum parcelamento cadastrado para a marca '{marca}': o produto não pode ser financiado."
    return {
        'valor': produto.valor,
        'entrada': produto.entrada_cliente if entrada is None else entrada,
        'opcoes': opcoes,
        'aviso': aviso,
    }


def simulacao_do_detalhe(produto: Produto) -> dict:
    """Simulação com a entrada mínima; problemas de cadastro viram `aviso` (não erro)."""
    try:
        return simular_parcelas(produto)
    except ErroDeNegocio as erro:
        return {'valor': produto.valor, 'entrada': produto.entrada_cliente, 'opcoes': [], 'aviso': erro.mensagem}


def mesclar_lojas(atuais: set[int], enviadas: set[int], escopo: set[int] | None) -> set[int]:
    """Lojas finais de um vínculo M2M editado por quem só enxerga `escopo`.

    As enviadas precisam estar no escopo (`escopo=None` = todas); as atuais fora do
    escopo são preservadas, pois quem edita não as vê nem pode removê-las.
    """
    if escopo is None:
        return set(enviadas)
    return set(enviadas) | (set(atuais) - escopo)
