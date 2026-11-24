"""Pix fixo (chave da empresa, sem baixa automática): payload copia-e-cola e imagem do QR Code."""
import base64
from io import BytesIO

import qrcode
from pypix import Pix


def payload_pix(chave: str, valor: str, txid: str, nome_loja: str, cidade_loja: str,
                descricao: str | None = None) -> str:
    pix = Pix()
    pix.set_pixkey(chave)
    pix.set_amount(valor)
    pix.set_txid(txid)
    pix.set_merchant_name(nome_loja[:25])
    pix.set_merchant_city(cidade_loja[:15])
    if descricao:
        pix.set_description(descricao[:30])
    return str(pix)


def qr_code_base64(texto: str) -> str:
    """PNG do QR Code em base64 (sem o prefixo `data:`)."""
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(texto)
    qr.make(fit=True)
    buffer = BytesIO()
    qr.make_image().save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')
