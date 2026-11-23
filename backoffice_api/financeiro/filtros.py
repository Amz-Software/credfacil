"""Filtros e ordenação da lista de contas a receber (`?busca=`, `?status=`...)."""
import re

from django.db.models import Exists, OuterRef, Q, QuerySet

from vendas.models import Pagamento, Parcela

from ..nucleo.erros import PROIBIDO_ACESSO, VALIDACAO, ErroBackoffice
from .constantes import (
    FILTRO_PAGAMENTO_EFETUADO,
    FILTROS_SITUACAO,
    ORDENACAO_LISTA,
    ORDENACAO_PADRAO,
    STATUS_ATRASADO,
    STATUS_LISTA,
    STATUS_NO_PRAZO,
    STATUS_PENDENTE,
    STATUS_QUITADO,
)

# Busca por número do pagamento: ids com mais dígitos estouram o inteiro do banco.
MAXIMO_DIGITOS_ID = 10
PADRAO_CPF = re.compile(r'[\d.\-\s]+')


def base_contas_a_receber() -> QuerySet:
    """Pagamentos parcelados de vendas ativas, como na tela Django (sem ENTRADA nem caixa)."""
    return (
        Pagamento.objects.exclude(venda__is_deleted=True)
        .with_status_flags()
        .exclude(tipo_pagamento__caixa=True)
        .filter(tipo_pagamento__parcelas=True)
    )


def _erro_campo(campo: str, mensagem: str) -> ErroBackoffice:
    return ErroBackoffice('Revise os filtros informados.', codigo=VALIDACAO, campos={campo: [mensagem]})


def _filtrar_busca(queryset: QuerySet, termo: str) -> QuerySet:
    termo = termo.strip()
    if not termo:
        return queryset
    condicao = Q(venda__cliente__nome__icontains=termo) | Q(venda__cliente__contatos__observacao__icontains=termo)
    if PADRAO_CPF.fullmatch(termo):
        digitos = re.sub(r'\D', '', termo)
        if digitos:
            condicao |= Q(venda__cliente__cpf__icontains=digitos)
    if termo.isdigit() and len(termo) <= MAXIMO_DIGITOS_ID:
        condicao |= Q(pk=int(termo))
    # Subconsulta: a junção com contatos não duplica linhas nem mexe nas contagens anotadas.
    return queryset.filter(pk__in=Pagamento.objects.filter(condicao).values('pk'))


def _filtrar_status(queryset: QuerySet, status: str) -> QuerySet:
    if status not in STATUS_LISTA:
        raise _erro_campo('status', f'Use um destes valores: {", ".join(STATUS_LISTA)}.')
    if status == STATUS_NO_PRAZO:
        # Mesma regra da tela: ao menos uma parcela paga.
        return queryset.filter(Exists(Parcela.objects.filter(pagamento=OuterRef('pk'), pago=True)))
    filtros = {
        STATUS_ATRASADO: {'com_parcela_atrasada': True},
        STATUS_QUITADO: {'todas_parcelas_pagas': True},
        STATUS_PENDENTE: {'com_pagamento_pendente': True},
    }
    return queryset.filter(**filtros[status])


def _ids_inteiros(valores: list[str], campo: str) -> list[int]:
    ids = []
    for valor in valores:
        valor = valor.strip()
        if not valor.isdigit() or len(valor) > MAXIMO_DIGITOS_ID:
            raise _erro_campo(campo, 'Informe ids numéricos.')
        ids.append(int(valor))
    return ids


def _filtrar_status_pagamento(queryset: QuerySet, valores: list[str]) -> QuerySet:
    ids = _ids_inteiros(valores, 'status_pagamento')
    return queryset.filter(pk__in=Pagamento.objects.filter(statuses__in=ids).values('pk'))


def _filtrar_situacoes(queryset: QuerySet, situacoes: list[str]) -> QuerySet:
    for situacao in situacoes:
        if situacao not in FILTROS_SITUACAO:
            raise _erro_campo('situacao', f'Use um destes valores: {", ".join(FILTROS_SITUACAO)}.')
        if situacao == FILTRO_PAGAMENTO_EFETUADO:
            queryset = queryset.filter(
                Exists(Parcela.objects.filter(pagamento=OuterRef('pk'), pagamento_efetuado=True))
            )
        else:
            queryset = queryset.filter(**{situacao: True})
    return queryset


def _filtrar_loja(queryset: QuerySet, valor: str, pode_filtrar_loja: bool) -> QuerySet:
    if not pode_filtrar_loja:
        raise ErroBackoffice(
            'Você não tem permissão para filtrar por loja.', codigo=PROIBIDO_ACESSO, status_http=403,
        )
    (loja_id,) = _ids_inteiros([valor], 'loja')
    return queryset.filter(loja_id=loja_id)


def ordenar(queryset: QuerySet, valor: str) -> QuerySet:
    valor = (valor or ORDENACAO_PADRAO).strip()
    decrescente = valor.startswith('-')
    chave = valor.lstrip('-')
    if chave not in ORDENACAO_LISTA:
        raise _erro_campo('ordenar', f'Use um destes campos: {", ".join(ORDENACAO_LISTA)}.')
    campo = f'-{ORDENACAO_LISTA[chave]}' if decrescente else ORDENACAO_LISTA[chave]
    return queryset.order_by(campo) if chave == 'id' else queryset.order_by(campo, '-id')


def filtrar_contas(queryset: QuerySet, params, *, pode_filtrar_loja: bool) -> QuerySet:
    """Aplica os filtros de `params` (QueryDict); valor inválido vira 400 com `campos`."""
    if params.get('busca'):
        queryset = _filtrar_busca(queryset, params['busca'])
    if params.get('status'):
        queryset = _filtrar_status(queryset, params['status'])
    if params.get('loja'):
        queryset = _filtrar_loja(queryset, params['loja'], pode_filtrar_loja)
    status_pagamento = [v for v in params.getlist('status_pagamento') if v]
    if status_pagamento:
        queryset = _filtrar_status_pagamento(queryset, status_pagamento)
    situacoes = [v for v in params.getlist('situacao') if v]
    if situacoes:
        queryset = _filtrar_situacoes(queryset, situacoes)
    return ordenar(queryset, params.get('ordenar', ''))
