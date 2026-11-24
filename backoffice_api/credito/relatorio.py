"""PDF das pré-análises rápidas: mesmo template e conteúdo de `vendas/views/pre_analise.py:PreAnaliseRapidaPDFView`."""
from django.db.models import QuerySet
from django.template.loader import get_template
from django.utils import timezone
import weasyprint

from vendas.models import Loja, PreAnaliseRapida

from .filtros import ROTULOS_STATUS_PRE_ANALISE, ler_lojas

TEMPLATE = 'pre_analise_rapida/pre_analise_rapida_pdf.html'
SEM_VALOR = '—'


def _linha(pre: PreAnaliseRapida) -> dict:
    rotulo = ROTULOS_STATUS_PRE_ANALISE.get(pre.status, pre.status)
    if pre.status == 'A' and pre.finalizada:
        rotulo = f'{rotulo} (Finalizada)'
    return {
        'cliente': pre.nome_completo,
        'cpf': pre.cpf,
        'loja': pre.loja.nome if pre.loja else SEM_VALOR,
        'status': rotulo,
        'enviado_em': timezone.localtime(pre.criado_em).strftime('%d/%m/%Y %H:%M'),
    }


def _lojas_do_filtro(params) -> str:
    ids = ler_lojas(params)
    if not ids:
        return 'Todas'
    return ', '.join(Loja.objects.filter(pk__in=ids).order_by('nome').values_list('nome', flat=True)) or 'Todas'


def gerar_pdf_pre_analises(
    pre_analises: QuerySet, params, tamanho_pagina: str = 'A4 landscape',
) -> tuple[bytes, int]:
    """Devolve (bytes do PDF, quantidade de linhas)."""
    linhas = [_linha(pre) for pre in pre_analises]
    html = get_template(TEMPLATE).render({
        'linhas': linhas,
        'total': len(linhas),
        'loja_filtro': _lojas_do_filtro(params),
        'status_filtro': ROTULOS_STATUS_PRE_ANALISE.get(params.get('status', ''), 'Todos'),
        'data_inicio': params.get('data_inicio', '') or SEM_VALOR,
        'data_fim': params.get('data_fim', '') or SEM_VALOR,
        'gerado_em': timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M'),
        'tamanho_pagina': tamanho_pagina,
    })
    return weasyprint.HTML(string=html).write_pdf(), len(linhas)


def nome_do_arquivo() -> str:
    return f'pre_analises_rapidas_{timezone.localtime(timezone.now()):%Y%m%d_%H%M%S}.pdf'
