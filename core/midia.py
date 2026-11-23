"""Mídia local (sem S3) servida só com URL assinada.

`MidiaAssinadaStorage.url(nome)` devolve `/mediafiles/<nome>?assinatura=<token>`;
o token é um `TimestampSigner` sobre o nome do arquivo e vale
`MIDIA_ASSINATURA_HORAS` horas. Assim templates, API e a SPA do vendedor
(que monta `<img src>` sem cabeçalho de autenticação) continuam recebendo URLs
que funcionam, mas quem só conhece o caminho (ou um link antigo) recebe 404.

A view `servir_midia` confere a assinatura e entrega o arquivo pelo Django
(`FileResponse`) ou, com `MIDIA_X_ACCEL_PREFIXO` definido, delega ao nginx por
`X-Accel-Redirect` para um `location` marcado como `internal`.
"""
import mimetypes
import os
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.utils._os import safe_join
from django.views.decorators.http import require_GET

PARAMETRO_ASSINATURA = 'assinatura'
SAL_ASSINATURA = 'core.midia.url'
SEGUNDOS_POR_HORA = 3600
# Abrem no navegador; o resto vai como anexo (HTML/SVG nunca é renderizado na origem).
TIPOS_INLINE = frozenset({'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'application/pdf'})


def _assinador() -> signing.TimestampSigner:
    return signing.TimestampSigner(salt=SAL_ASSINATURA)


def _normalizar(nome: str) -> str:
    return str(nome).replace('\\', '/').lstrip('/')


def assinar(nome: str) -> str:
    """Token (`timestamp:assinatura`) para o arquivo `nome`."""
    nome = _normalizar(nome)
    return _assinador().sign(nome)[len(nome) + 1:]


def assinatura_valida(nome: str, token: str) -> bool:
    if not token:
        return False
    validade = int(getattr(settings, 'MIDIA_ASSINATURA_HORAS', 6)) * SEGUNDOS_POR_HORA
    nome = _normalizar(nome)
    try:
        return _assinador().unsign(f'{nome}:{token}', max_age=validade) == nome
    except signing.BadSignature:  # inclui SignatureExpired
        return False


class MidiaAssinadaStorage(FileSystemStorage):
    """`FileSystemStorage` do MEDIA_ROOT cuja URL leva a assinatura temporária."""

    def url(self, name):
        url = super().url(name)
        return f'{url}?{PARAMETRO_ASSINATURA}={quote(assinar(name), safe=":")}'


def _caminho_seguro(caminho: str) -> str:
    """Caminho absoluto dentro do MEDIA_ROOT, ou 404 (`..`, absoluto, NUL, fora da raiz)."""
    partes = caminho.replace('\\', '/').split('/')
    if not caminho or '\x00' in caminho or caminho.startswith('/') or '..' in partes:
        raise Http404
    try:
        absoluto = safe_join(settings.MEDIA_ROOT, caminho)
    except (SuspiciousFileOperation, ValueError):
        raise Http404
    if not os.path.isfile(absoluto):
        raise Http404
    return absoluto


def _cabecalhos(resposta: HttpResponse, nome: str, tipo: str) -> HttpResponse:
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Cache-Control'] = 'private, max-age=3600'
    if tipo not in TIPOS_INLINE:
        nome_arquivo = quote(os.path.basename(nome))
        resposta['Content-Disposition'] = f"attachment; filename*=UTF-8''{nome_arquivo}"
    return resposta


@require_GET
def servir_midia(request: HttpRequest, caminho: str) -> HttpResponse:
    if not assinatura_valida(caminho, request.GET.get(PARAMETRO_ASSINATURA, '')):
        raise Http404
    absoluto = _caminho_seguro(caminho)
    tipo = mimetypes.guess_type(absoluto)[0] or 'application/octet-stream'

    prefixo = getattr(settings, 'MIDIA_X_ACCEL_PREFIXO', '')
    if prefixo:
        resposta = HttpResponse(content_type=tipo)
        resposta['X-Accel-Redirect'] = f"{prefixo.rstrip('/')}/{quote(_normalizar(caminho))}"
        return _cabecalhos(resposta, caminho, tipo)

    resposta = FileResponse(open(absoluto, 'rb'), content_type=tipo)
    return _cabecalhos(resposta, caminho, tipo)
