"""Validação única de upload: tipo pelos bytes do arquivo (não pela extensão nem pelo
`content_type` enviado pelo cliente) e tamanho máximo.

A detecção por assinatura (`mime_pelos_bytes`) é a mesma do CRM de WhatsApp
(`crm/services/midias.py` reaproveita esta função).
"""
from django.core.exceptions import ValidationError

MB = 1024 * 1024
TAMANHO_MAXIMO_UPLOAD = 10 * MB
BYTES_PARA_DETECCAO = 16

TIPOS_IMAGEM = frozenset({'image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/heic'})
TIPOS_DOCUMENTO = TIPOS_IMAGEM | {'application/pdf'}


def mime_pelos_bytes(conteudo: bytes) -> str:
    """MIME pela assinatura (magic number) dos primeiros bytes; '' se desconhecido."""
    inicio = conteudo[:BYTES_PARA_DETECCAO]
    assinaturas = (
        (b'\xff\xd8\xff', 'image/jpeg'), (b'\x89PNG', 'image/png'), (b'GIF8', 'image/gif'),
        (b'%PDF', 'application/pdf'), (b'OggS', 'audio/ogg'), (b'\x1aE\xdf\xa3', 'video/webm'),
        (b'ID3', 'audio/mpeg'), (b'\xff\xfb', 'audio/mpeg'), (b'#!AMR', 'audio/amr'),
    )
    for assinatura, mime in assinaturas:
        if inicio.startswith(assinatura):
            return mime
    if inicio[:4] == b'RIFF' and inicio[8:12] == b'WEBP':
        return 'image/webp'
    if inicio[:4] == b'RIFF' and inicio[8:12] == b'WAVE':
        return 'audio/wav'
    if inicio[4:8] == b'ftyp':
        marca = inicio[8:12]
        if marca in (b'heic', b'heix', b'mif1', b'msf1', b'heim', b'heis'):
            return 'image/heic'
        if marca in (b'M4A ', b'M4B '):
            return 'audio/mp4'
        return 'video/mp4'
    return ''


def _primeiros_bytes(arquivo) -> bytes:
    posicao = arquivo.tell() if hasattr(arquivo, 'tell') else 0
    arquivo.seek(0)
    inicio = arquivo.read(BYTES_PARA_DETECCAO)
    arquivo.seek(posicao)
    return inicio


def validar_upload(
    arquivo,
    tipos_aceitos: frozenset[str] = TIPOS_DOCUMENTO,
    tamanho_maximo: int = TAMANHO_MAXIMO_UPLOAD,
) -> str:
    """Levanta `ValidationError` (mensagem para o usuário) ou devolve o MIME detectado."""
    if arquivo.size > tamanho_maximo:
        raise ValidationError(
            f'Arquivo muito grande. Máximo: {tamanho_maximo // MB} MB.', code='arquivo_grande',
        )
    mime = mime_pelos_bytes(_primeiros_bytes(arquivo))
    if mime not in tipos_aceitos:
        aceitos = 'imagem (JPG, PNG, WEBP, GIF ou HEIC)'
        if 'application/pdf' in tipos_aceitos:
            aceitos += ' ou PDF'
        raise ValidationError(f'Tipo de arquivo não aceito. Envie {aceitos}.', code='tipo_invalido')
    return mime


def validar_documento(arquivo) -> None:
    """Validador de campo (DRF/Django): imagem ou PDF, até 10 MB."""
    validar_upload(arquivo)


def validar_imagem(arquivo) -> None:
    """Validador de campo (DRF/Django): só imagem, até 10 MB."""
    validar_upload(arquivo, TIPOS_IMAGEM)


def erros_de_upload(arquivos, tipos_aceitos: frozenset[str] = TIPOS_DOCUMENTO) -> dict[str, list[str]]:
    """Erros por campo de um `request.FILES` (vazio quando todos os arquivos são válidos)."""
    erros: dict[str, list[str]] = {}
    for campo in arquivos:
        for arquivo in arquivos.getlist(campo):
            try:
                validar_upload(arquivo, tipos_aceitos)
            except ValidationError as erro:
                erros.setdefault(campo, []).extend(erro.messages)
    return erros
