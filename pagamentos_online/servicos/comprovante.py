"""Comprovante em PDF de um pagamento PagBank, anexado a cada parcela paga, como os comprovantes manuais."""
import logging

from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.utils import timezone

from vendas.models import ComprovanteParcela

from ..models import Cobranca
from .planos import rotulo_da_cobranca

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
        'itens': cobranca.itens_da_baixa(),
        'rotulo': rotulo_da_cobranca(cobranca),
        'quitacao': cobranca.tipo == Cobranca.Tipo.QUITACAO,
        'cliente': parcela.pagamento.venda.cliente,
        'paga_em': timezone.localtime(cobranca.paga_em) if cobranca.paga_em else None,
        'emitido_em': timezone.localtime(),
    }
    html = render_to_string(TEMPLATE, contexto)
    return weasyprint.HTML(string=html, url_fetcher=buscar_recurso_local).write_pdf()


def nome_para_download(cobranca: Cobranca) -> str:
    if cobranca.tipo == Cobranca.Tipo.QUITACAO:
        return 'comprovante-quitacao.pdf'
    numeros = '-'.join(str(n) for n in cobranca.numeros_das_parcelas())
    return f'comprovante-parcela-{numeros}.pdf'


def anexar_comprovante(cobranca_id: int) -> list[ComprovanteParcela]:
    """Gera o PDF uma vez e anexa em cada parcela da cobrança (não duplica se já estiver anexado)."""
    cobranca = Cobranca.objects.select_related('parcela__pagamento__venda__cliente', 'parcela__pagamento__loja').get(
        pk=cobranca_id)
    if cobranca.status != Cobranca.Status.PAGA:
        return []
    nome = nome_do_arquivo(cobranca)
    observacao = f'Pago via PagBank ({cobranca.get_forma_display()}), pedido {cobranca.pagbank_pedido_id}'[:255]
    conteudo = None
    anexados = []
    for item in cobranca.itens_da_baixa():
        existente = item.parcela.comprovantes.filter(arquivo__endswith=nome).first()
        if existente:
            anexados.append(existente)
            continue
        conteudo = conteudo or gerar_pdf(cobranca)
        comprovante = ComprovanteParcela(parcela=item.parcela, loja=cobranca.parcela.pagamento.loja,
                                         observacao=observacao)
        comprovante.arquivo.save(nome, ContentFile(conteudo), save=False)
        comprovante.save()
        anexados.append(comprovante)
    return anexados
