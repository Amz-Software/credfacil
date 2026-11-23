"""Mídia: download da Meta, miniatura, validação do anexo, conversão, transcrição e URL assinada."""
import base64
import hashlib
import io
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
from datetime import timedelta

import requests
from django.core.files import File
from django.core.files.base import ContentFile
from django.utils import timezone

from core.uploads import mime_pelos_bytes
from crm.models import Mensagem, Midia
from crm.whatsapp import ErroWhatsApp, modo_integracao, obter_provider

logger = logging.getLogger(__name__)

MB = 1024 * 1024
LIMITE_RECEBIDO = {
    Mensagem.Tipo.IMAGEM: 5 * MB,
    Mensagem.Tipo.VIDEO: 16 * MB,
    Mensagem.Tipo.AUDIO: 16 * MB,
    Mensagem.Tipo.FIGURINHA: MB // 2,
    Mensagem.Tipo.DOCUMENTO: 100 * MB,
}
LIMITE_ENVIO = 25 * MB
LIMITE_IMAGEM_META = 5 * MB
LIMITE_VIDEO_META = 16 * MB
LADO_MINIATURA = 320
MAX_TENTATIVAS = 20
AUDIO_ACEITO_META = {'audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/amr', 'audio/ogg'}
TIMEOUT_FFMPEG = 120
TIMEOUT_TRANSCRICAO = 60
MIMES_HEIC = {'image/heic', 'image/heif'}


class ErroMidia(Exception):
    pass


# --- identificação ------------------------------------------------------------

# Detecção pelos bytes compartilhada com o validador de upload da API (core/uploads.py).
_mime_pelos_bytes = mime_pelos_bytes


def validar_anexo(conteudo: bytes, nome: str) -> tuple[str, str]:
    """Devolve (tipo interno, mime). O tipo vem dos bytes, não da extensão."""
    if not conteudo:
        raise ErroMidia('O arquivo está vazio.')
    if len(conteudo) > LIMITE_ENVIO:
        raise ErroMidia('O arquivo passa de 25 MB.')
    mime = _mime_pelos_bytes(conteudo) or mimetypes.guess_type(nome or '')[0] or 'application/octet-stream'
    if mime in MIMES_HEIC:
        raise ErroMidia('Fotos HEIC/HEIF não são aceitas. Envie em JPG ou PNG.')
    if mime in ('image/jpeg', 'image/png', 'image/webp', 'image/gif'):
        return Mensagem.Tipo.IMAGEM, mime
    if mime.startswith('video/') and mime != 'video/webm':
        return Mensagem.Tipo.VIDEO, mime
    if mime.startswith('audio/') or mime == 'video/webm':
        return Mensagem.Tipo.AUDIO, 'audio/webm' if mime == 'video/webm' else mime
    return Mensagem.Tipo.DOCUMENTO, mime


# --- recebida --------------------------------------------------------------------

TIPOS_COM_MINIATURA = (Mensagem.Tipo.IMAGEM, Mensagem.Tipo.FIGURINHA, Mensagem.Tipo.VIDEO)


def _sha256_do_arquivo(caminho: str) -> bytes:
    resumo = hashlib.sha256()
    with open(caminho, 'rb') as arquivo:
        for bloco in iter(lambda: arquivo.read(MB), b''):
            resumo.update(bloco)
    return resumo.digest()


def _confere_sha(digest: bytes, anunciado: str) -> bool:
    if not anunciado:
        return True
    return anunciado in (digest.hex(), base64.b64encode(digest).decode())


def _falhar(midia: Midia, motivo: str) -> None:
    midia.status, midia.erro, midia.tentativas = Midia.Status.ERRO, motivo, midia.tentativas + 1
    midia.save(update_fields=['status', 'erro', 'tentativas'])


def baixar(midia: Midia) -> None:
    """Baixa da Meta e guarda no storage privado. Falha → ERRO (o cron tenta de novo)."""
    if midia.status in (Midia.Status.OK, Midia.Status.EXPIRADA) or not midia.wa_media_id:
        return
    mensagem = midia.mensagem
    limite = LIMITE_RECEBIDO.get(mensagem.tipo, LIMITE_ENVIO)
    try:
        caminho, mime, sha = obter_provider().baixar_midia(midia.wa_media_id, limite)
    except ErroWhatsApp as exc:
        _falhar(midia, str(exc))
        return
    try:
        tamanho = os.path.getsize(caminho)
        if not tamanho:
            _falhar(midia, 'A Meta entregou um arquivo vazio.')
            return
        if not _confere_sha(_sha256_do_arquivo(caminho), midia.sha256 or sha):
            _falhar(midia, 'O arquivo chegou corrompido (SHA-256 diferente).')
            return
        midia.mime = midia.mime or mime
        extensao = mimetypes.guess_extension((midia.mime or '').split(';')[0]) or '.bin'
        nome = midia.nome_original or f'{mensagem.tipo.lower()}{extensao}'
        with open(caminho, 'rb') as arquivo:
            midia.arquivo.save(nome, File(arquivo), save=False)
        midia.tamanho_bytes = tamanho
        if mensagem.tipo in TIPOS_COM_MINIATURA:
            with open(caminho, 'rb') as arquivo:
                _metadados_e_miniatura(midia, arquivo.read())
        midia.status, midia.erro, midia.baixado_em = Midia.Status.OK, '', timezone.now()
        midia.save()
    finally:
        os.unlink(caminho)


def _metadados_e_miniatura(midia: Midia, conteudo: bytes) -> None:
    tipo = midia.mensagem.tipo
    if tipo in (Mensagem.Tipo.IMAGEM, Mensagem.Tipo.FIGURINHA):
        try:
            from PIL import Image

            with Image.open(io.BytesIO(conteudo)) as imagem:
                midia.largura, midia.altura = imagem.size
                copia = imagem.convert('RGB')
                copia.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
                saida = io.BytesIO()
                copia.save(saida, format='JPEG', quality=80)
                midia.miniatura.save('miniatura.jpg', ContentFile(saida.getvalue()), save=False)
        except Exception:  # noqa: BLE001 — sem miniatura a mídia continua válida
            logger.info('Miniatura não gerada para a mídia %s.', midia.pk)
    elif tipo == Mensagem.Tipo.VIDEO and _ffmpeg():
        quadro = _rodar_ffmpeg(conteudo, ['-ss', '1', '-frames:v', '1', '-vf', f'scale={LADO_MINIATURA}:-2'], 'jpg')
        if quadro:
            midia.miniatura.save('miniatura.jpg', ContentFile(quadro), save=False)


# --- conversão para envio ---------------------------------------------------------

def _ffmpeg() -> str | None:
    return shutil.which(os.environ.get('FFMPEG_BIN', 'ffmpeg'))


def _rodar_ffmpeg(conteudo: bytes, argumentos: list[str], extensao: str) -> bytes | None:
    binario = _ffmpeg()
    if not binario:
        return None
    with tempfile.TemporaryDirectory() as pasta:
        entrada, saida = os.path.join(pasta, 'entrada'), os.path.join(pasta, f'saida.{extensao}')
        with open(entrada, 'wb') as arquivo:
            arquivo.write(conteudo)
        comando = [binario, '-y', '-loglevel', 'error', '-i', entrada, *argumentos, saida]
        try:
            subprocess.run(comando, check=True, timeout=TIMEOUT_FFMPEG, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            logger.warning('ffmpeg falhou ao converter mídia.', exc_info=True)
            return None
        with open(saida, 'rb') as arquivo:
            return arquivo.read()


def _converter_imagem(conteudo: bytes) -> bytes:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(conteudo)) as imagem:
            copia = imagem.convert('RGB')
    except Exception as exc:  # noqa: BLE001 — Pillow lança vários tipos para arquivo inválido
        raise ErroMidia('A imagem está corrompida ou em formato não suportado.') from exc
    for lado, qualidade in ((2560, 85), (1920, 75), (1280, 65)):
        reduzida = copia.copy()
        reduzida.thumbnail((lado, lado))
        saida = io.BytesIO()
        reduzida.save(saida, format='JPEG', quality=qualidade)
        if saida.tell() <= LIMITE_IMAGEM_META:
            return saida.getvalue()
    raise ErroMidia('Não foi possível reduzir a imagem para o limite da Meta (5 MB).')


def _nome_com_extensao(nome: str, extensao: str) -> str:
    base = (nome or 'arquivo').rsplit('.', 1)[0]
    return f'{base}.{extensao}'


def preparar_para_meta(midia: Midia) -> tuple[bytes, str, str]:
    """Converte quando a Meta exige e guarda a versão enviada. Devolve (bytes, mime, nome)."""
    with midia.arquivo.open('rb') as arquivo:
        conteudo = arquivo.read()
    tipo, mime, nome = midia.mensagem.tipo, midia.mime, midia.nome_original or 'arquivo'
    convertido, novo_mime, novo_nome = conteudo, mime, nome

    if tipo == Mensagem.Tipo.IMAGEM and (mime not in ('image/jpeg', 'image/png') or len(conteudo) > LIMITE_IMAGEM_META):
        convertido, novo_mime, novo_nome = _converter_imagem(conteudo), 'image/jpeg', _nome_com_extensao(nome, 'jpg')
    elif tipo == Mensagem.Tipo.AUDIO and (midia.voz or mime not in AUDIO_ACEITO_META):
        saida = _rodar_ffmpeg(conteudo, ['-vn', '-c:a', 'libopus', '-ac', '1', '-b:a', '32k'], 'ogg')
        if saida is None:
            raise ErroMidia('Não foi possível converter o áudio para o formato do WhatsApp.')
        convertido, novo_mime, novo_nome = saida, 'audio/ogg', _nome_com_extensao(nome, 'ogg')
    elif tipo == Mensagem.Tipo.VIDEO and (mime != 'video/mp4' or len(conteudo) > LIMITE_VIDEO_META):
        saida = _rodar_ffmpeg(conteudo, [
            '-c:v', 'libx264', '-profile:v', 'main', '-bf', '0', '-vf', "scale='min(720,iw)':-2",
            '-c:a', 'aac', '-movflags', '+faststart'], 'mp4')
        if saida is None or len(saida) > LIMITE_VIDEO_META:
            raise ErroMidia('Não foi possível converter o vídeo para o limite da Meta (16 MB, MP4).')
        convertido, novo_mime, novo_nome = saida, 'video/mp4', _nome_com_extensao(nome, 'mp4')

    if convertido is not conteudo:
        midia.arquivo_envio.save(novo_nome, ContentFile(convertido), save=False)
        midia.save(update_fields=['arquivo_envio'])
    return convertido, novo_mime, novo_nome


# --- transcrição --------------------------------------------------------------------

TEXTO_SEM_TRANSCRICAO = '[áudio não transcrito]'


def transcrever(mensagem: Mensagem) -> None:
    """Whisper da OpenAI, só com OPENAI_API_KEY e WhatsApp real. Falha não bloqueia nada."""
    if mensagem.transcricao_status != Mensagem.Transcricao.PENDENTE:
        return
    midia = getattr(mensagem, 'midia', None)
    if midia is None or midia.status != Midia.Status.OK:
        return
    chave = os.environ.get('OPENAI_API_KEY', '').strip()
    if not chave or modo_integracao() != 'real':
        mensagem.transcricao_status = Mensagem.Transcricao.ERRO
        mensagem.save(update_fields=['transcricao_status'])
        return
    try:
        with midia.arquivo.open('rb') as arquivo:
            resposta = requests.post(
                'https://api.openai.com/v1/audio/transcriptions',
                headers={'Authorization': f'Bearer {chave}'},
                data={'model': os.environ.get('TRANSCRICAO_MODELO', 'whisper-1'), 'language': 'pt'},
                files={'file': (os.path.basename(midia.arquivo.name), arquivo, midia.mime or 'audio/ogg')},
                timeout=TIMEOUT_TRANSCRICAO,
            )
        resposta.raise_for_status()
        texto = (resposta.json().get('text') or '').strip()
    except (requests.RequestException, ValueError):
        logger.warning('Transcrição falhou para a mensagem %s.', mensagem.pk, exc_info=True)
        texto = ''
    mensagem.texto = texto or TEXTO_SEM_TRANSCRICAO
    mensagem.transcricao_status = Mensagem.Transcricao.OK if texto else Mensagem.Transcricao.ERRO
    mensagem.save(update_fields=['texto', 'transcricao_status'])


# --- download pela tela ---------------------------------------------------------------

def campo_para_download(midia: Midia, versao: str):
    """Arquivo a entregar: a miniatura quando pedida e existente, senão o original."""
    if versao == 'miniatura' and midia.miniatura:
        return midia.miniatura
    return midia.arquivo
