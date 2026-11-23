"""Validação de imagens da loja (logo e QR code) pelo conteúdo."""
from PIL import Image
from rest_framework import serializers

TAMANHO_MAXIMO_BYTES = 10 * 1024 * 1024
FORMATOS_ACEITOS = ('PNG', 'JPEG', 'WEBP')


def validar_imagem(arquivo):
    """O DRF `ImageField` já abre com o Pillow; aqui conferimos tamanho e formato real."""
    if arquivo.size > TAMANHO_MAXIMO_BYTES:
        raise serializers.ValidationError('A imagem excede o limite de 10 MB.')
    arquivo.seek(0)
    try:
        with Image.open(arquivo) as imagem:
            formato = imagem.format
    except Exception:
        raise serializers.ValidationError('Envie uma imagem válida.')
    finally:
        arquivo.seek(0)
    if formato not in FORMATOS_ACEITOS:
        raise serializers.ValidationError('Formato de imagem não aceito. Use PNG, JPEG ou WEBP.')
    return arquivo
