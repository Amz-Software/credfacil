"""Filtros e ordenação da fila de solicitações e das pré-análises.

Os filtros são os mesmos de `vendas/filtros.py` (tela atual) e de
`vendas/views/pre_analise.py`; o escopo de loja não fica aqui, e sim no núcleo
(`BackofficeMixin.filtrar_por_lojas`).
"""
import re
from datetime import date, datetime, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_date

from api.views.solicitacoes_regras import _filtro_busca_solicitacao
from backoffice_api.nucleo.erros import ErroBackoffice
from vendas.models import AnaliseCreditoCliente, PreAnaliseRapida

from .regras import ROTULOS_STATUS, ROTULOS_STATUS_APP

VERDADEIROS = {'1', 'true', 'sim'}
FALSOS = {'0', 'false', 'nao', 'não'}
MIN_DIGITOS_BUSCA_CPF = 3

ORDENACAO_SOLICITACOES = {
    'id': 'id',
    'nome': 'nome',
    'data_analise': 'analise_credito__data_analise',
    'status': 'analise_credito__status',
    'loja': 'loja__nome',
    'produto': 'analise_credito__produto__nome',
}
ORDENACAO_PRE_ANALISES = {
    'id': 'id',
    'criado_em': 'criado_em',
    'nome_completo': 'nome_completo',
    'status': 'status',
    'data_decisao': 'data_decisao',
}
ROTULOS_STATUS_PRE_ANALISE = dict(PreAnaliseRapida.STATUS_CHOICES)


def _erro_campo(campo: str, mensagem: str) -> ErroBackoffice:
    return ErroBackoffice('Revise os filtros informados.', campos={campo: [mensagem]})


def inicio_do_dia(dia: date) -> datetime:
    """Primeiro instante do dia no fuso do projeto (evita `__date`, que depende do MySQL)."""
    return timezone.make_aware(datetime.combine(dia, datetime.min.time()))


def ler_data(params, campo: str) -> date | None:
    valor = (params.get(campo) or '').strip()
    if not valor:
        return None
    try:
        dia = parse_date(valor)
    except ValueError:
        dia = None
    if dia is None:
        raise _erro_campo(campo, 'Data inválida. Use o formato AAAA-MM-DD.')
    return dia


def ler_booleano(params, campo: str) -> bool | None:
    valor = (params.get(campo) or '').strip().lower()
    if not valor:
        return None
    if valor in VERDADEIROS:
        return True
    if valor in FALSOS:
        return False
    raise _erro_campo(campo, 'Use 1 (sim) ou 0 (não).')


def ler_escolha(params, campo: str, escolhas: dict) -> str | None:
    valor = (params.get(campo) or '').strip()
    if not valor:
        return None
    if valor not in escolhas:
        raise _erro_campo(campo, f'Valor inválido. Opções: {", ".join(escolhas)}.')
    return valor


def ler_lojas(params) -> list[int]:
    """`?loja=1&loja=2` ou `?loja=1,2`."""
    valores = []
    for item in params.getlist('loja'):
        valores.extend(parte.strip() for parte in str(item).split(',') if parte.strip())
    if any(not valor.isdigit() for valor in valores):
        raise _erro_campo('loja', 'Informe ids de loja numéricos.')
    return [int(valor) for valor in valores]


def _filtrar_periodo(qs: QuerySet, params, caminho: str) -> QuerySet:
    data_inicio = ler_data(params, 'data_inicio')
    data_fim = ler_data(params, 'data_fim')
    if data_inicio and data_fim and data_inicio > data_fim:
        raise _erro_campo('data_fim', 'A data final deve ser igual ou posterior à inicial.')
    if data_inicio:
        qs = qs.filter(**{f'{caminho}__gte': inicio_do_dia(data_inicio)})
    if data_fim:
        qs = qs.filter(**{f'{caminho}__lt': inicio_do_dia(data_fim + timedelta(days=1))})
    return qs


def termo_de_busca(params) -> str:
    return (params.get('busca') or params.get('termo') or '').strip()


def filtrar_solicitacoes(qs: QuerySet, params) -> QuerySet:
    """Filtros da fila: busca, loja(s), status, status_app, período, online e não finalizadas."""
    busca = termo_de_busca(params)
    if busca:
        qs = qs.filter(_filtro_busca_solicitacao(busca))

    lojas = ler_lojas(params)
    if lojas:
        qs = qs.filter(loja_id__in=lojas)

    status = ler_escolha(params, 'status', ROTULOS_STATUS)
    if status:
        qs = qs.filter(analise_credito__status=status)

    status_app = ler_escolha(params, 'status_app', ROTULOS_STATUS_APP)
    if status_app:
        qs = qs.filter(analise_credito__status_aplicativo=status_app)

    analise_online = ler_booleano(params, 'analise_online')
    if analise_online is not None:
        qs = qs.filter(analise_credito__analise_online=analise_online)

    if ler_booleano(params, 'vendas_nao_finalizadas'):
        qs = qs.filter(analise_credito__venda__isnull=True)

    return _filtrar_periodo(qs, params, 'analise_credito__data_analise')


def _campo_ordenacao(params, permitidos: dict) -> tuple[str, bool] | None:
    valor = (params.get('ordenar') or '').strip()
    if not valor:
        return None
    decrescente = valor.startswith('-')
    nome = valor.lstrip('-')
    if nome not in permitidos:
        raise _erro_campo('ordenar', f'Ordenação inválida. Opções: {", ".join(permitidos)}.')
    return permitidos[nome], decrescente


def ordenar_solicitacoes(qs: QuerySet, params) -> QuerySet:
    """Padrão: ordem de criação, da solicitação mais recente para a mais antiga."""
    escolhida = _campo_ordenacao(params, ORDENACAO_SOLICITACOES)
    if escolhida:
        caminho, decrescente = escolhida
        return qs.order_by(f'-{caminho}' if decrescente else caminho, '-id')
    return qs.order_by('-analise_credito__data_analise', '-id')


def _filtro_busca_pre_analise(termo: str) -> Q:
    filtro = Q(nome_completo__icontains=termo) | Q(cpf__icontains=termo)
    digitos = re.sub(r'\D', '', termo)
    if len(digitos) >= MIN_DIGITOS_BUSCA_CPF and digitos != termo:
        filtro |= Q(cpf__icontains=digitos)
    return filtro


def filtrar_pre_analises(qs: QuerySet, params) -> QuerySet:
    """Filtros da tela atual (busca, status, loja, período) + `finalizada` da API do vendedor."""
    busca = termo_de_busca(params) or (params.get('q') or '').strip()
    if busca:
        qs = qs.filter(_filtro_busca_pre_analise(busca))

    status = ler_escolha(params, 'status', ROTULOS_STATUS_PRE_ANALISE)
    if status:
        qs = qs.filter(status=status)

    lojas = ler_lojas(params)
    if lojas:
        qs = qs.filter(loja_id__in=lojas)

    finalizada = ler_booleano(params, 'finalizada')
    if finalizada is not None:
        qs = qs.filter(cliente_gerado__isnull=not finalizada)

    return _filtrar_periodo(qs, params, 'criado_em')


def ordenar_pre_analises(qs: QuerySet, params) -> QuerySet:
    escolhida = _campo_ordenacao(params, ORDENACAO_PRE_ANALISES)
    if not escolhida:
        return qs.order_by('-criado_em', '-id')
    caminho, decrescente = escolhida
    return qs.order_by(f'-{caminho}' if decrescente else caminho, '-id')


def analises_para_kpis(params) -> QuerySet:
    """Base dos contadores (o escopo de loja é aplicado pela view)."""
    qs = AnaliseCreditoCliente.objects.all()
    lojas = ler_lojas(params)
    if lojas:
        qs = qs.filter(loja_id__in=lojas)
    return qs
