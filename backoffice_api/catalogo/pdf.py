"""PDF da listagem de produtos (WeasyPrint), com o mesmo template da tela Django.

Os recursos do HTML (logo) são lidos dos arquivos estáticos locais: nada é buscado
pela rede (o domínio da SPA não serve `/static/` e isso evita SSRF).
"""
import logging
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.db.models import QuerySet
from django.template.loader import render_to_string
from django.utils import timezone

from produtos.models import Marca

logger = logging.getLogger(__name__)

TEMPLATE_PDF_PRODUTOS = 'produtos/produto_pdf.html'
BASE_URL_PDF = 'https://catalogo.local/'


class RecursoRecusado(ValueError):
    """URL fora dos arquivos estáticos locais."""


def _arquivo_estatico(url: str) -> str | None:
    caminho = urlparse(url).path
    if not caminho.startswith(settings.STATIC_URL):
        return None
    relativo = unquote(caminho[len(settings.STATIC_URL):])
    if '..' in Path(relativo).parts:
        return None
    return finders.find(relativo)


def buscar_recurso_local(url: str, *args, **kwargs) -> dict:
    """`url_fetcher` do WeasyPrint: só `data:` e arquivos de STATIC."""
    import weasyprint

    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url, *args, **kwargs)
    arquivo = _arquivo_estatico(url)
    if not arquivo:
        logger.warning('PDF do catálogo: recurso recusado (%s)', url[:200])
        raise RecursoRecusado(url)
    tipo, _ = mimetypes.guess_type(arquivo)
    return {'string': Path(arquivo).read_bytes(), 'mime_type': tipo or 'application/octet-stream'}


def gerar_pdf_produtos(
    produtos: QuerySet, *, busca: str, marca: Marca | None, tamanho_pagina: str = 'A4 landscape',
) -> bytes:
    import weasyprint

    html = render_to_string(TEMPLATE_PDF_PRODUTOS, {
        'produtos': produtos,
        'search': busca,
        'marca': marca,
        'gerado_em': timezone.localtime(timezone.now()),
        'tamanho_pagina': tamanho_pagina,
    })
    return weasyprint.HTML(string=html, base_url=BASE_URL_PDF, url_fetcher=buscar_recurso_local).write_pdf()
