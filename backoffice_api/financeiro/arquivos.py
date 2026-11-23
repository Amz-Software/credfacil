"""Validação dos comprovantes de parcela pelo conteúdo (não só pela extensão).

Mesma ideia de `crm/services/midias.py`: o tipo vem dos primeiros bytes do
arquivo. Mantém os limites da tela Django (extensões de `ComprovanteParcela` e
10 MB).
"""
import os

from rest_framework import serializers

from vendas.models import ComprovanteParcela

BYTES_ANALISADOS = 16
# Extensão aceita -> família de conteúdo esperada.
FAMILIA_POR_EXTENSAO = {
    'pdf': 'pdf',
    'jpg': 'imagem',
    'jpeg': 'imagem',
    'png': 'imagem',
    'webp': 'imagem',
    'heic': 'imagem',
}
MARCAS_HEIC = (b'heic', b'heix', b'mif1', b'msf1', b'heim', b'heis', b'hevc', b'hevx')


def familia_pelo_conteudo(inicio: bytes) -> str:
    """'pdf', 'imagem' ou '' a partir da assinatura do arquivo."""
    if inicio.startswith(b'%PDF'):
        return 'pdf'
    if inicio.startswith(b'\xff\xd8\xff') or inicio.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'imagem'
    if inicio[:4] == b'RIFF' and inicio[8:12] == b'WEBP':
        return 'imagem'
    if inicio[4:8] == b'ftyp' and inicio[8:12] in MARCAS_HEIC:
        return 'imagem'
    return ''


def _ler_inicio(arquivo) -> bytes:
    arquivo.seek(0)
    inicio = arquivo.read(BYTES_ANALISADOS)
    arquivo.seek(0)
    return inicio


def validar_comprovante(arquivo):
    """Levanta `ValidationError` com mensagem para o usuário; devolve o próprio arquivo."""
    if not arquivo or not arquivo.size:
        raise serializers.ValidationError('Selecione um arquivo para anexar.')
    if arquivo.size > ComprovanteParcela.TAMANHO_MAXIMO_BYTES:
        limite_mb = ComprovanteParcela.TAMANHO_MAXIMO_BYTES // (1024 * 1024)
        raise serializers.ValidationError(f'O arquivo excede o limite de {limite_mb} MB.')
    extensao = os.path.splitext(arquivo.name or '')[1].lstrip('.').lower()
    if extensao not in ComprovanteParcela.EXTENSOES_PERMITIDAS:
        permitidas = ', '.join(ComprovanteParcela.EXTENSOES_PERMITIDAS).upper()
        raise serializers.ValidationError(f'Formato não permitido. Use um destes: {permitidas}.')
    if familia_pelo_conteudo(_ler_inicio(arquivo)) != FAMILIA_POR_EXTENSAO[extensao]:
        raise serializers.ValidationError('O conteúdo do arquivo não corresponde a um PDF ou imagem válidos.')
    return arquivo
