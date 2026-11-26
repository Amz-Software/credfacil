"""Ajuda para testes de PDF: lê o tamanho da 1ª página (o dicionário pode estar comprimido)."""
import re
import zlib

_INICIO_STREAM = re.compile(rb'stream\r?\n')
_MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)')

A4_PAISAGEM = (842, 595)
A2_PAISAGEM = (1684, 1191)
A3_RETRATO = (842, 1191)


def _trechos(conteudo: bytes):
    yield conteudo
    # Descomprime a partir do início de cada stream: o zlib para sozinho no fim dos dados,
    # sem depender de achar "endstream" (os bytes comprimidos podem conter essa sequência).
    for inicio in _INICIO_STREAM.finditer(conteudo):
        try:
            yield zlib.decompressobj().decompress(conteudo[inicio.end():])
        except zlib.error:
            continue


def tamanho_da_pagina(conteudo: bytes) -> tuple[int, int]:
    """(largura, altura) em pontos da primeira página do PDF."""
    for trecho in _trechos(conteudo):
        caixa = _MEDIA_BOX.search(trecho)
        if caixa:
            x0, y0, x1, y1 = (float(v) for v in caixa.groups())
            return round(x1 - x0), round(y1 - y0)
    raise AssertionError('PDF sem /MediaBox')
