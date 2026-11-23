"""Documentos da venda: validação do upload pelo conteúdo, gravação e entrega autenticada."""
import mimetypes
import os
import uuid

from django.http import FileResponse, Http404
from rest_framework import serializers

TAMANHO_MAXIMO_BYTES = 10 * 1024 * 1024
BYTES_ASSINATURA = 16
TIPOS_IMAGEM = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp'}
TIPOS_POR_CAMPO = {
    'documento_assinado': {**TIPOS_IMAGEM, 'application/pdf': '.pdf'},
    'foto_cliente': TIPOS_IMAGEM,
    'imagem_imei': TIPOS_IMAGEM,
}
# Arquivos antigos podem ter qualquer extensão: só estes tipos abrem no navegador.
TIPOS_EXIBIVEIS = {'application/pdf', 'image/jpeg', 'image/png', 'image/webp', 'image/gif'}


def tipo_pelos_bytes(inicio: bytes) -> str:
    """Tipo do arquivo pela assinatura (mesma ideia de crm/services/midias.py)."""
    if inicio.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if inicio.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if inicio.startswith(b'%PDF'):
        return 'application/pdf'
    if inicio[:4] == b'RIFF' and inicio[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def validar_arquivo(campo: str, arquivo) -> str:
    """Confere tamanho e tipo real; devolve a extensão correta. Levanta ValidationError."""
    if arquivo.size == 0:
        raise serializers.ValidationError('O arquivo está vazio.')
    if arquivo.size > TAMANHO_MAXIMO_BYTES:
        raise serializers.ValidationError('O arquivo passa de 10 MB.')
    arquivo.seek(0)
    inicio = arquivo.read(BYTES_ASSINATURA)
    arquivo.seek(0)
    permitidos = TIPOS_POR_CAMPO[campo]
    tipo = tipo_pelos_bytes(inicio)
    if tipo not in permitidos:
        nomes = ', '.join(sorted({ext.lstrip('.').upper() for ext in permitidos.values()}))
        raise serializers.ValidationError(f'Formato não aceito. Envie {nomes}.')
    return permitidos[tipo]


def salvar_documentos(venda, arquivos: dict, user) -> list[str]:
    """Grava os arquivos enviados (nome gerado no servidor) e devolve os campos alterados."""
    campos = []
    for campo, arquivo in arquivos.items():
        extensao = validar_arquivo(campo, arquivo)
        arquivo.name = f'{campo}_{uuid.uuid4().hex[:12]}{extensao}'
        setattr(venda, campo, arquivo)
        campos.append(campo)
    venda.save(user=user, update_fields=campos + ['modificado_por', 'modificado_em'])
    return campos


def abrir_documento(venda, campo: str) -> FileResponse:
    """FileResponse do arquivo; 404 quando não há arquivo ou ele sumiu do storage."""
    arquivo = getattr(venda, campo)
    if not arquivo or not arquivo.name:
        raise Http404
    try:
        conteudo = arquivo.storage.open(arquivo.name, 'rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404
    nome = os.path.basename(arquivo.name)
    tipo = mimetypes.guess_type(nome)[0] or 'application/octet-stream'
    exibivel = tipo in TIPOS_EXIBIVEIS
    resposta = FileResponse(
        conteudo,
        content_type=tipo if exibivel else 'application/octet-stream',
        as_attachment=not exibivel,
        filename=nome,
    )
    resposta['X-Content-Type-Options'] = 'nosniff'
    resposta['Cache-Control'] = 'private, no-store'
    return resposta
