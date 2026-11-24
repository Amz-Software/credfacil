"""Tamanho de papel dos PDFs com listas (relatórios e produtos).

O PDF é gerado no servidor, então trocar o papel só na janela de impressão apenas
amplia a página. Com `?papel=A2&orientacao=paisagem` o WeasyPrint diagrama o
relatório na folha escolhida e cabem mais linhas por página.

Os valores vêm de uma lista fechada: o texto vai para o CSS (`@page { size: ... }`).
"""
from collections.abc import Mapping

from .erros import ErroBackoffice

PAPEIS = {'A4': 'A4', 'A3': 'A3', 'A2': 'A2', 'A1': 'A1', 'carta': 'letter', 'oficio': 'legal'}
ORIENTACOES = {'paisagem': 'landscape', 'retrato': 'portrait'}
PAPEL_PADRAO = 'A4'
ORIENTACAO_PADRAO = 'paisagem'


def _escolha(parametros: Mapping, nome: str, opcoes: dict, padrao: str) -> str:
    valor = (parametros.get(nome) or padrao).strip()
    if valor not in opcoes:
        mensagem = f'Valor inválido. Opções: {", ".join(opcoes)}.'
        raise ErroBackoffice(mensagem, campos={nome: [mensagem]})
    return opcoes[valor]


def tamanho_pagina(parametros: Mapping) -> str:
    """Valor de `@page { size }` a partir de `papel` e `orientacao` (padrão A4 paisagem)."""
    papel = _escolha(parametros, 'papel', PAPEIS, PAPEL_PADRAO)
    orientacao = _escolha(parametros, 'orientacao', ORIENTACOES, ORIENTACAO_PADRAO)
    return f'{papel} {orientacao}'
