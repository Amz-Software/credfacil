import io
import os
from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile


def converter_para_webp(arquivo, qualidade=85):
    """
    Converte qualquer imagem enviada (JPG, PNG, WebP, etc.) para WebP.
    Retorna um InMemoryUploadedFile pronto para ser salvo em FileField/ImageField.
    """
    try:
        img = Image.open(arquivo)

        # Preserva transparência (PNG/WebP com alpha) convertendo para RGBA se necessário
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=qualidade, method=4)
        buffer.seek(0)

        nome_base = os.path.splitext(arquivo.name)[0]
        nome_webp = f"{nome_base}.webp"

        return InMemoryUploadedFile(
            file=buffer,
            field_name=arquivo.field_name if hasattr(arquivo, "field_name") else None,
            name=nome_webp,
            content_type="image/webp",
            size=buffer.getbuffer().nbytes,
            charset=None,
        )
    except Exception:
        # Se falhar a conversão (ex: PDF enviado como arquivo), devolve o original
        arquivo.seek(0)
        return arquivo
