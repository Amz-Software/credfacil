"""Comprovantes e fotos: validação de upload e entrega autenticada do arquivo.

O tipo é conferido pelos bytes do arquivo (mesma ideia de `crm/services/midias.py`),
nunca pela extensão ou pelo `content_type` enviado pelo navegador.
"""
import os
from dataclasses import dataclass

from django.http import FileResponse

from backoffice_api.nucleo.erros import NAO_ENCONTRADO_RECURSO, ErroBackoffice

MB = 1024 * 1024
TAMANHO_MAXIMO = 10 * MB
BYTES_CABECALHO = 16
MIMES_ACEITOS = ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')
MIMES_HEIC = ('image/heic', 'image/heif')
MIME_GENERICO = 'application/octet-stream'


@dataclass(frozen=True)
class DefinicaoArquivo:
    campo: str
    rotulo: str
    origem: str  # 'comprovantes' | 'analise' | 'pre_analise'
    serasa: bool = False


ARQUIVOS_SOLICITACAO = {
    definicao.campo: definicao
    for definicao in (
        DefinicaoArquivo('documento_identificacao_frente', 'Documento de identificação (frente)', 'comprovantes'),
        DefinicaoArquivo('documento_identificacao_verso', 'Documento de identificação (verso)', 'comprovantes'),
        DefinicaoArquivo('comprovante_residencia', 'Comprovante de residência', 'comprovantes'),
        DefinicaoArquivo('foto_cliente', 'Foto do cliente', 'comprovantes'),
        DefinicaoArquivo('consulta_serasa', 'Consulta Serasa', 'comprovantes', serasa=True),
        DefinicaoArquivo('consulta_serasa_2', 'Consulta Serasa 2', 'comprovantes', serasa=True),
        DefinicaoArquivo('codigo_reserva', 'Código de reserva', 'analise'),
    )
}
ARQUIVOS_PRE_ANALISE = {
    definicao.campo: definicao
    for definicao in (
        DefinicaoArquivo('foto_rg_frente', 'Foto do RG (frente)', 'pre_analise'),
        DefinicaoArquivo('foto_rg_verso', 'Foto do RG (verso)', 'pre_analise'),
        DefinicaoArquivo('consulta_serasa', 'Consulta Serasa', 'pre_analise', serasa=True),
    )
}
TIPO_SERASA = {'consulta_serasa': 'serasa', 'consulta_serasa_2': 'serasa_2'}


def mime_pelos_bytes(inicio: bytes) -> str:
    assinaturas = (
        (b'%PDF', 'application/pdf'),
        (b'\xff\xd8\xff', 'image/jpeg'),
        (b'\x89PNG', 'image/png'),
    )
    for assinatura, mime in assinaturas:
        if inicio.startswith(assinatura):
            return mime
    if inicio[:4] == b'RIFF' and inicio[8:12] == b'WEBP':
        return 'image/webp'
    if inicio[4:8] == b'ftyp' and inicio[8:12] in (b'heic', b'heix', b'mif1', b'msf1', b'heim', b'heis'):
        return 'image/heic'
    return ''


def _ler_cabecalho(arquivo) -> bytes:
    posicao = arquivo.tell() if hasattr(arquivo, 'tell') else 0
    arquivo.seek(0)
    inicio = arquivo.read(BYTES_CABECALHO)
    arquivo.seek(posicao)
    return inicio


def erro_do_upload(arquivo) -> str | None:
    """Mensagem de erro do arquivo enviado, ou None se ele for aceito."""
    if not arquivo or not getattr(arquivo, 'size', 0):
        return 'O arquivo está vazio.'
    if arquivo.size > TAMANHO_MAXIMO:
        return 'O arquivo passa de 10 MB.'
    mime = mime_pelos_bytes(_ler_cabecalho(arquivo))
    if mime in MIMES_HEIC:
        return 'Fotos HEIC/HEIF não são aceitas. Envie em JPG ou PNG.'
    if mime not in MIMES_ACEITOS:
        return 'Formato não aceito. Envie PDF, JPG, PNG ou WEBP.'
    return None


def validar_uploads(arquivos: dict) -> None:
    """Valida todos os arquivos enviados ({campo: arquivo}); 400 com os campos inválidos."""
    erros = {}
    for campo, arquivo in arquivos.items():
        mensagem = erro_do_upload(arquivo)
        if mensagem:
            erros[campo] = [mensagem]
    if erros:
        raise ErroBackoffice('Revise os arquivos enviados.', campos=erros)


def responder_arquivo(campo_arquivo, *, download: bool = False) -> FileResponse:
    """Entrega o arquivo pelo Django (funciona com disco e S3) com cabeçalhos seguros.

    Só PDF e imagem abrem no navegador; qualquer outro tipo vai como download genérico.
    """
    if not campo_arquivo or not getattr(campo_arquivo, 'name', ''):
        raise ErroBackoffice('Arquivo não encontrado.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
    try:
        arquivo = campo_arquivo.open('rb')
        mime = mime_pelos_bytes(_ler_cabecalho(arquivo))
    except (OSError, ValueError):
        raise ErroBackoffice('Arquivo não encontrado.', codigo=NAO_ENCONTRADO_RECURSO, status_http=404)
    em_linha = mime in MIMES_ACEITOS and not download
    resposta = FileResponse(
        arquivo,
        as_attachment=not em_linha,
        filename=os.path.basename(campo_arquivo.name),
        content_type=mime if mime in MIMES_ACEITOS else MIME_GENERICO,
    )
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Cache-Control'] = 'private, no-store'
    return resposta
