"""PDFs da venda gerados no servidor (WeasyPrint): nota, carnê/promissória e contrato.

O conteúdo é o mesmo das telas antigas (`venda/venda_pdf.html`, `venda/folha_carne.html`
e `venda/contrato.html`). Imagens entram como data URI e o WeasyPrint não acessa a rede.
"""
import base64
import io
import logging
import mimetypes
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

import weasyprint
from dateutil.relativedelta import relativedelta
from django.contrib.staticfiles import finders
from django.template import Context, Engine
from django.utils import timezone
from django.utils.safestring import mark_safe

from vendas.models import Loja
from vendas.services.erros import ErroDeNegocio

from .editorjs import editorjs_para_html
from .regras import pagamento_carne
from .serializers import nome_do_usuario

logger = logging.getLogger(__name__)

PASTA_TEMPLATES = Path(__file__).resolve().parent / 'templates_pdf'
_MOTOR = Engine(dirs=[str(PASTA_TEMPLATES)], autoescape=True)
LOGO_IPIX = 'images/IPIX.png'
LOGO_CREDFACIL = 'images/logo.png'
OPACIDADE_MARCA_DAGUA = 0.15
TIPOS_CARNE = {'carne': 'Carnê', 'promissoria': 'Promissória'}
# Dias de tolerância escritos em cada via do contrato (iguais aos da tela atual).
VIAS_CONTRATO = (('VIA DO CLIENTE', 3), ('VIA DO LOJISTA', 5))
PIX_NOME = 'CredFacil'
PIX_CIDADE = 'Belem'


# --- formatação -----------------------------------------------------------------------

def moeda(valor) -> str:
    """1234.5 → '1.234,50'."""
    valor = Decimal(valor or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    inteiro, _, centavos = f'{valor:,.2f}'.partition('.')
    return f"{inteiro.replace(',', '.')},{centavos}"


def data(valor) -> str:
    return valor.strftime('%d/%m/%Y') if valor else ''


def data_hora(valor) -> str:
    return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M') if valor else ''


def formatar_cpf(cpf: str | None) -> str:
    digitos = ''.join(c for c in (cpf or '') if c.isdigit())
    if len(digitos) != 11:
        return cpf or ''
    return f'{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}'


def _com_opacidade(conteudo: bytes, opacidade: float) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(conteudo)) as imagem:
        rgba = imagem.convert('RGBA')
    alfa = rgba.getchannel('A').point(lambda valor: int(valor * opacidade))
    rgba.putalpha(alfa)
    saida = io.BytesIO()
    rgba.save(saida, format='PNG')
    return saida.getvalue()


@lru_cache(maxsize=8)
def imagem_estatica(caminho: str, opacidade: float | None = None) -> str | None:
    """Imagem de `static/` como data URI (None se o arquivo não existir)."""
    arquivo = finders.find(caminho)
    if not arquivo:
        return None
    with open(arquivo, 'rb') as origem:
        conteudo = origem.read()
    if opacidade is not None:
        conteudo = _com_opacidade(conteudo, opacidade)
    tipo = 'image/png' if opacidade is not None else (mimetypes.guess_type(arquivo)[0] or 'image/png')
    return f'data:{tipo};base64,{base64.b64encode(conteudo).decode()}'


# --- renderização --------------------------------------------------------------------

def _buscador_sem_rede(url, *args, **kwargs):
    """Só aceita data URI: o PDF nunca busca nada na rede nem no disco."""
    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url)
    raise ValueError('Recurso externo bloqueado no PDF.')


def renderizar_pdf(template: str, contexto: dict) -> bytes:
    html = _MOTOR.get_template(template).render(Context(contexto))
    return weasyprint.HTML(string=html, url_fetcher=_buscador_sem_rede).write_pdf()


def _loja(loja) -> dict:
    if loja is None:
        return {'nome': '', 'endereco': '', 'cnpj': '', 'telefone': ''}
    return {
        'nome': loja.nome, 'endereco': loja.endereco or '', 'cnpj': loja.cnpj or '',
        'telefone': loja.telefone or '',
    }


# --- nota --------------------------------------------------------------------------

def contexto_nota(venda) -> dict:
    cliente = venda.cliente
    itens = list(venda.itens_venda.all())
    return {
        'logo': imagem_estatica(LOGO_IPIX),
        'emitido_em': data_hora(timezone.now()),
        'venda': {
            'numero': venda.pk, 'data': data_hora(venda.data_venda),
            'vendedor': nome_do_usuario(venda.vendedor),
        },
        'loja': _loja(venda.loja),
        'mensagem_garantia': (venda.loja.mensagem_garantia if venda.loja else '') or '',
        'cliente': {
            'nome': cliente.nome,
            'telefones': [t for t in (cliente.telefone, cliente.telefone_secundario) if t],
            'cpf': formatar_cpf(cliente.cpf), 'email': cliente.email or '',
            'endereco': cliente.endereco, 'cep': cliente.cep, 'cidade': cliente.cidade,
            'uf': getattr(cliente, 'uf', '') or '',
        },
        'itens': [
            {
                'codigo': item.produto.codigo or '', 'nome': item.produto.nome, 'imei': item.imei or '',
                'quantidade': item.quantidade, 'valor_unitario': moeda(item.valor_unitario),
                'valor_desconto': moeda(item.valor_desconto), 'valor_total': moeda(item.calcular_valor_total()),
            }
            for item in itens
        ],
        'total': moeda(sum((item.calcular_valor_total() for item in itens), Decimal('0'))),
        'pagamentos': [
            {
                'tipo': pagamento.tipo_pagamento.nome, 'valor': moeda(pagamento.valor),
                'parcelas': pagamento.parcelas, 'primeiro_vencimento': data(pagamento.data_primeira_parcela),
            }
            for pagamento in venda.pagamentos.all()
        ],
    }


# --- carnê -------------------------------------------------------------------------

def _qr_pix(chave: str, valor: str, txid: str, descricao: str) -> str:
    from vendas.views.vendas import gerar_qrcode_pix

    try:
        return gerar_qrcode_pix(
            chave=chave, valor=valor, txid=txid, nome_loja=PIX_NOME, cidade_loja=PIX_CIDADE, descricao=descricao,
        )
    except Exception as exc:  # noqa: BLE001 — pypix/qrcode lançam tipos variados para dado inválido
        logger.warning('Falha ao gerar QR Code PIX do carnê (txid %s): %s', txid, exc)
        raise ErroDeNegocio('Não foi possível gerar o QR Code PIX. Confira a chave PIX da loja CredFacil.')


def contexto_carne(venda, tipo: str) -> dict:
    """Uma folha por parcela do pagamento em carnê, com QR Code PIX (regra de `folha_carne_view`)."""
    pagamento = pagamento_carne(venda)
    if pagamento is None:
        raise ErroDeNegocio('Esta venda não tem pagamento em carnê ou promissória.')
    loja_pix = Loja.objects.filter(credfacil=True).order_by('pk').first()
    if loja_pix is None or not loja_pix.chave_pix:
        raise ErroDeNegocio('Cadastre a loja CredFacil com chave PIX para gerar o carnê.')
    cliente = venda.cliente
    parcelas = list(pagamento.parcelas_pagamento.all())
    quantidade = pagamento.parcelas or len(parcelas)
    # Como na tela: o valor da parcela vem sempre do pagamento (valor / parcelas).
    valor_parcela = pagamento.valor / pagamento.parcelas if pagamento.parcelas else pagamento.valor
    valor_pix = f'{valor_parcela:.2f}'
    folhas = [
        {
            'numero': indice,
            'vencimento': data(parcela.data_vencimento),
            'valor': moeda(valor_parcela),
            'qr_code': _qr_pix(
                loja_pix.chave_pix, valor_pix, f'{pagamento.pk:04d}{indice:02d}',
                f'{cliente.nome} - Parcela {indice} de {quantidade}',
            ),
        }
        for indice, parcela in enumerate(parcelas, start=1)
    ]
    return {
        'logo': imagem_estatica(LOGO_CREDFACIL),
        'tipo_pagamento': TIPOS_CARNE[tipo],
        'venda': {'numero': venda.pk, 'loja': venda.loja.nome if venda.loja else ''},
        'cliente': {'nome': cliente.nome.title(), 'cpf': formatar_cpf(cliente.cpf)},
        'credor': {**_loja(loja_pix), 'chave_pix': loja_pix.chave_pix},
        'quantidade_parcelas': quantidade,
        'data_emissao': data(timezone.localdate()),
        'folhas': folhas,
    }


# --- contrato ---------------------------------------------------------------------

def contexto_contrato(venda) -> dict:
    """Contrato de locação com o texto Editor.js da loja da venda convertido e sanitizado."""
    loja = venda.loja
    if loja is None:
        raise ErroDeNegocio('Esta venda não tem loja; não há contrato para gerar.')
    pagamento = pagamento_carne(venda)
    aparelho = next(iter(venda.itens_venda.all()), None)
    primeira = pagamento.data_primeira_parcela if pagamento else None
    quantidade = (pagamento.parcelas or 0) if pagamento else 0
    ultima = primeira + relativedelta(months=quantidade - 1) if primeira and quantidade else None
    cliente = venda.cliente
    return {
        'logo': imagem_estatica(LOGO_IPIX),
        'marca_dagua': imagem_estatica(LOGO_CREDFACIL, OPACIDADE_MARCA_DAGUA),
        'loja': _loja(loja),
        'cliente': {
            'nome': cliente.nome, 'cpf': formatar_cpf(cliente.cpf), 'rg': cliente.rg,
            'endereco': cliente.endereco,
        },
        'aparelho': aparelho.produto.nome if aparelho else '',
        'imei': (aparelho.imei if aparelho else '') or '',
        'primeira_parcela': data(primeira),
        'ultima_parcela': data(ultima),
        'valor_parcela': moeda(pagamento.valor / pagamento.parcelas) if pagamento and pagamento.parcelas else '-',
        'quantidade_parcelas': quantidade,
        'texto_contrato': mark_safe(editorjs_para_html(loja.contrato)),  # noqa: S308 — sanitizado
        'vias': [{'titulo': titulo, 'dias_tolerancia': dias} for titulo, dias in VIAS_CONTRATO],
    }
