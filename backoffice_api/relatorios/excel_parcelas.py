"""Planilha do relatório de parcelas: mesma grade colorida de `RelatorioParcelasExcelView`.

Extraída de financeiro/views.py (a tela antiga continua com a dela). Verde = pago,
vermelho = atrasado, amarelo = a vencer.
"""
from io import BytesIO

import openpyxl
from django.utils import timezone
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .servicos.parcelas import ATRASADO, PAGO

FILL_CABECALHO = PatternFill('solid', fgColor='ED7D31')
FILL_PAGO = PatternFill('solid', fgColor='92D050')
FILL_ATRASADO = PatternFill('solid', fgColor='FF0000')
FILL_A_VENCER = PatternFill('solid', fgColor='FFC000')
LINHA_FINA = Side(style='thin', color='C9A27E')
BORDA = Border(left=LINHA_FINA, right=LINHA_FINA, top=LINHA_FINA, bottom=LINHA_FINA)
COLUNAS_FIXAS = 3   # Loja, Cliente, Aparelho
COLUNAS_TOTAIS = 4  # Total, Pago, Atrasado, A vencer
LINHA_CABECALHO = 5
LARGURAS_FIXAS = {'A': 18, 'B': 24, 'C': 26}
LARGURA_PARCELA = 14
LARGURA_TOTAL = 13


def brl(valor) -> str:
    """1234.5 -> 'R$ 1.234,50'."""
    texto = f'{float(valor or 0):,.2f}'
    return 'R$ ' + texto.replace(',', 'X').replace('.', ',').replace('X', '.')


def _estilo_parcela(situacao: str) -> tuple[PatternFill, Font]:
    if situacao == PAGO:
        return FILL_PAGO, Font(bold=True)
    if situacao == ATRASADO:
        return FILL_ATRASADO, Font(bold=True, color='FFFFFF')
    return FILL_A_VENCER, Font(bold=True)


def _titulo_e_legenda(ws, total_colunas: int, quantidade: int) -> None:
    titulo = ws.cell(row=1, column=1, value='Relatório de Parcelas')
    titulo.font = Font(bold=True, size=16, color='7A3E00')
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_colunas)
    gerado = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    sub = ws.cell(row=2, column=1, value=f'Gerado em {gerado} • {quantidade} cliente(s)')
    sub.font = Font(italic=True, color='7A7A7A')
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=total_colunas)
    ws.cell(row=3, column=1, value='Legenda:').font = Font(bold=True)
    for indice, (texto, fill, branco) in enumerate([
        ('Pago', FILL_PAGO, False), ('Atrasado', FILL_ATRASADO, True), ('A vencer', FILL_A_VENCER, False),
    ]):
        celula = ws.cell(row=3, column=2 + indice, value=texto)
        celula.fill, celula.border = fill, BORDA
        celula.alignment = Alignment(horizontal='center')
        celula.font = Font(bold=True, color='FFFFFF') if branco else Font(bold=True)


def _cabecalho(ws, max_parcelas: int) -> None:
    textos = ['Loja', 'Cliente', 'Aparelho'] + [str(i) for i in range(1, max_parcelas + 1)] + [
        'Total', 'Pago', 'Atrasado', 'A vencer',
    ]
    for coluna, texto in enumerate(textos, start=1):
        celula = ws.cell(row=LINHA_CABECALHO, column=coluna, value=texto)
        celula.fill, celula.border = FILL_CABECALHO, BORDA
        celula.font = Font(bold=True, color='FFFFFF')
        celula.alignment = Alignment(horizontal='center', vertical='center')


def _linha(ws, numero_linha: int, dados: dict, max_parcelas: int) -> None:
    for coluna, valor in enumerate((dados['loja'], dados['cliente'], dados['aparelho']), start=1):
        ws.cell(row=numero_linha, column=coluna, value=valor).border = BORDA
    for parcela in dados['parcelas']:
        coluna = COLUNAS_FIXAS + parcela['numero']
        if coluna > COLUNAS_FIXAS + max_parcelas:
            continue
        vencimento = parcela['vencimento'].strftime('%d/%m/%Y') if parcela['vencimento'] else ''
        celula = ws.cell(row=numero_linha, column=coluna, value=f"{brl(parcela['valor'])}\n{vencimento}")
        celula.fill, celula.font = _estilo_parcela(parcela['situacao'])
        celula.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        celula.border = BORDA
    base = COLUNAS_FIXAS + max_parcelas
    totais = (dados['total'], dados['total_pago'], dados['total_atrasado'], dados['total_a_vencer'])
    for deslocamento, valor in enumerate(totais, start=1):
        celula = ws.cell(row=numero_linha, column=base + deslocamento, value=brl(valor))
        celula.border = BORDA
        celula.alignment = Alignment(horizontal='right')


def _layout(ws, max_parcelas: int) -> None:
    for letra, largura in LARGURAS_FIXAS.items():
        ws.column_dimensions[letra].width = largura
    for i in range(1, max_parcelas + 1):
        ws.column_dimensions[get_column_letter(COLUNAS_FIXAS + i)].width = LARGURA_PARCELA
    for i in range(1, COLUNAS_TOTAIS + 1):
        ws.column_dimensions[get_column_letter(COLUNAS_FIXAS + max_parcelas + i)].width = LARGURA_TOTAL
    ws.freeze_panes = ws.cell(row=LINHA_CABECALHO + 1, column=COLUNAS_FIXAS + 1)
    ws.sheet_view.showGridLines = False


def gerar_planilha(linhas: list[dict]) -> bytes:
    max_parcelas = max([1] + [len(l['parcelas']) for l in linhas])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Parcelamento'
    _titulo_e_legenda(ws, COLUNAS_FIXAS + max_parcelas + COLUNAS_TOTAIS, len(linhas))
    _cabecalho(ws, max_parcelas)
    for deslocamento, dados in enumerate(linhas, start=1):
        _linha(ws, LINHA_CABECALHO + deslocamento, dados, max_parcelas)
    _layout(ws, max_parcelas)
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
