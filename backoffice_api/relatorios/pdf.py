"""Geração de PDF no servidor (WeasyPrint) e entrega de arquivos pela API do backoffice.

Os recursos do HTML (logo, CSS) são lidos só dos arquivos estáticos locais: nenhuma
URL externa é buscada (evita SSRF e dependência de rede durante a geração).
"""
import logging
import mimetypes
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

import weasyprint
from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template import engines
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_URL_PDF = 'https://relatorio.local/'
PASTA_TEMPLATES = Path(__file__).resolve().parent / 'templates'
TIPO_PDF = 'application/pdf'
TIPO_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class RecursoBloqueado(ValueError):
    """URL fora dos arquivos estáticos locais."""


def _arquivo_estatico(caminho_url: str) -> str | None:
    prefixo = settings.STATIC_URL
    if not caminho_url.startswith(prefixo):
        return None
    relativo = unquote(caminho_url[len(prefixo):])
    if '..' in Path(relativo).parts:
        return None
    return finders.find(relativo)


def buscar_recurso_local(url: str) -> dict:
    """`url_fetcher` do WeasyPrint: `data:` e arquivos de STATIC; o resto é recusado."""
    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url)
    caminho = _arquivo_estatico(urlparse(url).path)
    if not caminho:
        logger.warning('PDF do backoffice: recurso recusado (%s)', url[:200])
        raise RecursoBloqueado(url)
    tipo, _ = mimetypes.guess_type(caminho)
    return {'string': Path(caminho).read_bytes(), 'mime_type': tipo or 'application/octet-stream'}


def gerar_pdf(html: str) -> bytes:
    return weasyprint.HTML(string=html, base_url=BASE_URL_PDF, url_fetcher=buscar_recurso_local).write_pdf()


@lru_cache(maxsize=None)
def _template_local(nome: str):
    """Template de `relatorios/templates/` (fora das pastas do carregador padrão).

    Usa o motor padrão do Django, então `{% extends "components/report_base.html" %}`
    e `{% static %}` funcionam normalmente.
    """
    conteudo = (PASTA_TEMPLATES / nome).read_text(encoding='utf-8')
    return engines['django'].from_string(conteudo)


def renderizar_template_local(nome: str, contexto: dict) -> str:
    return _template_local(nome).render(contexto)


def nome_arquivo(prefixo: str, extensao: str) -> str:
    return f'{prefixo}_{timezone.localtime():%Y%m%d_%H%M%S}.{extensao}'


def resposta_arquivo(conteudo: bytes, tipo: str, nome: str) -> HttpResponse:
    resposta = HttpResponse(conteudo, content_type=tipo)
    resposta['Content-Disposition'] = f'attachment; filename="{nome}"'
    resposta['Cache-Control'] = 'no-store'
    resposta['X-Content-Type-Options'] = 'nosniff'
    return resposta


def resposta_pdf(html: str, prefixo: str) -> HttpResponse:
    return resposta_arquivo(gerar_pdf(html), TIPO_PDF, nome_arquivo(prefixo, 'pdf'))


class EntregaDeArquivoMixin:
    """Views que devolvem arquivo: aceitam qualquer `Accept` (os erros continuam em JSON)."""

    def perform_content_negotiation(self, request, force=False):
        return super().perform_content_negotiation(request, force=True)
