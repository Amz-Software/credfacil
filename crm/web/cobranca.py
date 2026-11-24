"""Relatórios da cobrança (/crm/cobranca/): painel de indicadores e listas por situação de contato."""
from datetime import date

from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET

from crm.services import relatorios_cobranca as relatorios
from crm.services.contatos import Status
from crm.services.relatorios_cobranca import Filtros, Relatorio
from crm.web.base import acesso_crm, gerencia_crm, inteiro_ou_none

ABA_PAINEL = 'painel'
ABAS = (ABA_PAINEL, *Relatorio.ROTULOS)
ROTULOS_ABAS = {ABA_PAINEL: 'Painel', **Relatorio.ROTULOS}
ESTADO_STATUS = {
    Status.CONTATO_REALIZADO: 'success',
    Status.AGUARDANDO_RETORNO: 'info',
    Status.CONTATO_ALTERNATIVO: 'primary',
    Status.REFERENCIA_SEM_SUCESSO: 'warning',
    Status.NUMERO_INVALIDO: 'danger',
    Status.SEM_WHATSAPP: 'warning',
    Status.BLOQUEIO_CONFIRMADO: 'danger',
    Status.NAO_LOCALIZADO: 'danger',
    Status.SEM_TENTATIVA: 'secondary',
}


def _data(valor: str | None) -> date | None:
    try:
        return parse_date(valor or '')
    except ValueError:
        return None


def ler_filtros(dados: QueryDict, hoje: date | None = None) -> Filtros:
    """Filtros da URL; valores inválidos voltam ao padrão (últimos 30 dias)."""
    padrao = Filtros.padrao(hoje)
    desde = _data(dados.get('desde')) or padrao.desde
    ate = _data(dados.get('ate')) or padrao.ate
    if desde > ate:
        desde, ate = ate, desde
    dia = inteiro_ou_none(dados.get('dia'))
    status = dados.get('status') or None
    return Filtros(
        desde=desde, ate=ate,
        dia_vencimento=dia if dia in relatorios.DIAS_VENCIMENTO else None,
        data_vencimento=_data(dados.get('vencimento')),
        status=status if status in Status.ROTULOS else None,
    )


def _abas(aba_atual: str, contagens: dict) -> list[dict]:
    return [{'chave': chave, 'rotulo': ROTULOS_ABAS[chave], 'ativa': chave == aba_atual,
             'contagem': contagens.get(chave)} for chave in ABAS]


def _consulta_sem(dados: QueryDict, *chaves: str) -> str:
    copia = dados.copy()
    for chave in chaves:
        copia.pop(chave, None)
    return copia.urlencode()


@require_GET
@acesso_crm
@gerencia_crm
def painel(request: HttpRequest) -> HttpResponse:
    hoje = timezone.localdate()
    filtros = ler_filtros(request.GET, hoje)
    aba = request.GET.get('aba') if request.GET.get('aba') in ABAS else ABA_PAINEL
    itens = relatorios.fichas(filtros, hoje, usuario=request.user)
    contexto = {
        'filtros': filtros, 'aba': aba, 'dias_vencimento': relatorios.DIAS_VENCIMENTO,
        'status_opcoes': list(Status.ROTULOS.items()),
        'consulta_filtros': _consulta_sem(request.GET, 'aba', 'page'),
    }
    if aba == ABA_PAINEL:
        contexto['indicadores'] = relatorios.indicadores(filtros, hoje, itens)
        contexto['abas'] = _abas(aba, relatorios.contagens(itens))
        return render(request, 'crm/cobranca/painel.html', contexto)
    resultado = relatorios.relatorio(aba, filtros, request.GET.get('page') or 1, hoje, itens)
    contexto.update({
        'resultado': resultado, 'titulo_aba': ROTULOS_ABAS[aba], 'page_obj': resultado.pagina, 'abas': _abas(aba, resultado.contagens),
        'linhas': [{'dados': linha, 'estado': ESTADO_STATUS.get(linha.ficha.status, 'secondary')}
                   for linha in resultado.linhas],
    })
    return render(request, 'crm/cobranca/lista.html', contexto)
