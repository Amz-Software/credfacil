"""Comprovante em PDF de um pagamento PagBank, anexado à parcela como os comprovantes manuais."""
import logging

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from vendas.models import ComprovanteParcela

from ..models import Cobranca

logger = logging.getLogger(__name__)

TEMPLATE = 'pagamentos_online/comprovante_pdf.html'


def nome_do_arquivo(cobranca: Cobranca) -> str:
    return f'pagbank-{cobranca.referencia}.pdf'


def gerar_pdf(cobranca: Cobranca) -> bytes:
    import weasyprint

    from backoffice_api.financeiro.bo import buscar_recurso_local

    parcela = cobranca.parcela
    contexto = {
        'cobranca': cobranca,
        'parcela': parcela,
        'cliente': parcela.pagamento.venda.cliente,
        'paga_em': timezone.localtime(cobranca.paga_em) if cobranca.paga_em else None,
        'emitido_em': timezone.localtime(),
    }
    html = render_to_string(TEMPLATE, contexto)
    return weasyprint.HTML(string=html, url_fetcher=buscar_recurso_local).write_pdf()


def anexar_comprovante(cobranca_id: int) -> ComprovanteParcela | None:
    cobranca = (Cobranca.objects.select_related('parcela__pagamento__venda__cliente', 'parcela__pagamento__loja')
                .get(pk=cobranca_id))
    if cobranca.status != Cobranca.Status.PAGA:
        return None
    nome = nome_do_arquivo(cobranca)
    existente = cobranca.parcela.comprovantes.filter(arquivo__endswith=nome).first()
    if existente:
        return existente
    comprovante = ComprovanteParcela(
        parcela=cobranca.parcela, loja=cobranca.parcela.pagamento.loja,
        observacao=f'Pago via PagBank ({cobranca.get_forma_display()}), pedido {cobranca.pagbank_pedido_id}'[:255],
    )
    comprovante.arquivo.save(nome, ContentFile(gerar_pdf(cobranca)), save=False)
    comprovante.save()
    return comprovante
