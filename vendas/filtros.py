"""Filtros compartilhados da listagem de solicitações (clientes).

Usado pela tela de listagem (`ClienteListView`) e pela exportação em Excel,
garantindo que o arquivo exportado reflita exatamente o que está filtrado
na tela.
"""

from vendas.models import Cliente

PERMISSAO_VER_TODAS_ANALISES = 'vendas.view_all_analise_credito'


def lojas_selecionadas(request) -> list[str]:
    """IDs das lojas marcadas no filtro múltiplo, ignorando valores vazios."""
    return [loja_id for loja_id in request.GET.getlist('loja') if loja_id]


def filtrar_clientes_solicitacao(request):
    """Aplica os filtros da listagem de solicitações e devolve o queryset.

    Respeita o escopo por loja: quem não tem permissão de ver todas as
    análises enxerga apenas a loja da sessão, independente do filtro enviado.
    """
    params = request.GET
    qs = Cliente.objects.all()

    status_app = params.get('status_app')
    if status_app:
        qs = qs.filter(analise_credito__status_aplicativo=status_app).distinct()

    search = params.get('search')
    if search:
        qs = qs.filter(nome__icontains=search)

    analise_online = params.get('analise_online')
    if analise_online == '1':
        qs = qs.filter(analise_credito__analise_online=True).distinct()
    elif analise_online == '0':
        qs = qs.filter(analise_credito__analise_online=False).distinct()

    status = params.get('status')
    if status:
        qs = qs.filter(analise_credito__status=status).distinct()

    lojas = lojas_selecionadas(request)
    if lojas:
        qs = qs.filter(loja_id__in=lojas)

    data_inicio = params.get('data_inicio')
    data_fim = params.get('data_fim')
    if data_inicio and data_fim:
        qs = qs.filter(analise_credito__data_analise__range=[data_inicio, data_fim]).distinct()
    elif data_inicio:
        qs = qs.filter(analise_credito__data_analise__gte=data_inicio).distinct()
    elif data_fim:
        qs = qs.filter(analise_credito__data_analise__lte=data_fim).distinct()

    if params.get('vendas_nao_finalizadas'):
        qs = qs.filter(analise_credito__venda__isnull=True).distinct()

    if not request.user.has_perm(PERMISSAO_VER_TODAS_ANALISES):
        qs = qs.filter(loja_id=request.session.get('loja_id'))

    return qs.order_by('-id')
