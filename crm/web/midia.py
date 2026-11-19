"""Entrega da mídia privada do CRM: permissão, log de acesso, Range (áudio/vídeo) e S3."""
import re

from django.http import FileResponse, Http404, HttpRequest, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from crm.models import LogAcessoMidia, Mensagem, Midia
from crm.services import midias
from crm.web.base import acesso_crm

MIMES_EM_LINHA = ('image/jpeg', 'image/png', 'image/webp', 'image/gif', 'video/', 'audio/')
VALIDADE_URL_S3_S = 300
TAMANHO_BLOCO = 64 * 1024
RANGE = re.compile(r'^bytes=(\d*)-(\d*)$')


def _ip_do_cliente(request: HttpRequest) -> str | None:
    """Último salto do X-Forwarded-For (o que o nginx do servidor acrescentou); o primeiro é forjável."""
    encaminhado = [parte.strip() for parte in (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',') if parte.strip()]
    return encaminhado[-1] if encaminhado else request.META.get('REMOTE_ADDR')


def _registrar_acesso(request: HttpRequest, arquivo_midia: Midia) -> None:
    LogAcessoMidia.objects.create(
        midia=arquivo_midia, usuario=request.user, ip=_ip_do_cliente(request),
        user_agent=(request.headers.get('User-Agent') or '')[:300],
    )


def _intervalo(cabecalho: str, tamanho: int) -> tuple[int, int] | None:
    """(início, fim) inclusivos de um 'Range: bytes=a-b' simples; None se ausente ou inválido."""
    achado = RANGE.match(cabecalho.strip()) if cabecalho else None
    if not achado or tamanho <= 0:
        return None
    inicio_txt, fim_txt = achado.groups()
    if not inicio_txt and not fim_txt:
        return None
    if not inicio_txt:  # sufixo: os últimos N bytes
        inicio, fim = max(tamanho - int(fim_txt), 0), tamanho - 1
    else:
        inicio, fim = int(inicio_txt), min(int(fim_txt) if fim_txt else tamanho - 1, tamanho - 1)
    return (inicio, fim) if inicio <= fim else None


def _blocos(arquivo, restante: int):
    try:
        while restante > 0:
            dados = arquivo.read(min(TAMANHO_BLOCO, restante))
            if not dados:
                break
            restante -= len(dados)
            yield dados
    finally:
        arquivo.close()


def _resposta_parcial(arquivo, intervalo: tuple[int, int], tamanho: int, mime: str) -> StreamingHttpResponse:
    inicio, fim = intervalo
    arquivo.seek(inicio)
    resposta = StreamingHttpResponse(_blocos(arquivo, fim - inicio + 1), status=206, content_type=mime)
    resposta['Content-Range'] = f'bytes {inicio}-{fim}/{tamanho}'
    resposta['Content-Length'] = str(fim - inicio + 1)
    return resposta


def _cabecalhos_comuns(resposta: HttpResponse) -> HttpResponse:
    resposta['Cache-Control'] = 'private, max-age=3600'
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Accept-Ranges'] = 'bytes'
    return resposta


@require_GET
@acesso_crm
def midia(request: HttpRequest, mensagem_id: int) -> HttpResponse:
    """Miniatura não entra no log (aparece a cada recarga); abrir o original entra."""
    mensagem = get_object_or_404(Mensagem.objects.select_related('midia'), pk=mensagem_id)
    arquivo_midia = getattr(mensagem, 'midia', None)
    if arquivo_midia is None or arquivo_midia.status != Midia.Status.OK:
        raise Http404('Mídia não encontrada.')
    versao = 'miniatura' if request.GET.get('versao') == 'miniatura' else ''
    campo = midias.campo_para_download(arquivo_midia, versao)
    if not campo:
        raise Http404('Mídia não encontrada.')
    if not versao:
        _registrar_acesso(request, arquivo_midia)
    if getattr(campo.storage, 'querystring_auth', False):  # S3: o navegador baixa direto, com Range nativo
        return HttpResponseRedirect(campo.storage.url(campo.name, expire=VALIDADE_URL_S3_S))
    try:
        arquivo = campo.open('rb')
        tamanho = campo.size
    except OSError:
        raise Http404('Mídia não encontrada.')
    mime = 'image/jpeg' if versao else (arquivo_midia.mime or 'application/octet-stream')
    em_linha = mime.startswith(MIMES_EM_LINHA)  # SVG, HTML e afins só como download
    tipo = mime if em_linha else 'application/octet-stream'
    intervalo = _intervalo(request.headers.get('Range', ''), tamanho) if em_linha else None
    if intervalo:
        return _cabecalhos_comuns(_resposta_parcial(arquivo, intervalo, tamanho, tipo))
    resposta = FileResponse(arquivo, as_attachment=not em_linha, filename=arquivo_midia.nome_original or None,
                            content_type=tipo)
    return _cabecalhos_comuns(resposta)
