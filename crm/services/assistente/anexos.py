"""Imagens e PDFs que o cliente manda: o assistente vê o arquivo e anexa o comprovante na parcela.

O comprovante entra como na página pública ("pagamento informado"): a parcela para de ser
cobrada e a equipe confere e dá baixa pelo fluxo que já existe (notificação aos analistas).
"""
import base64
import logging
import os
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from crm.models import Conversa, Mensagem, Midia

logger = logging.getLogger(__name__)

JANELA_COMPROVANTE = timedelta(hours=2)
JANELA_VISAO = timedelta(minutes=30)
MAX_ANEXOS_VISTOS = 2
MAX_BYTES_VISAO = 3_500_000
TIPOS_ANEXO = (Mensagem.Tipo.IMAGEM, Mensagem.Tipo.DOCUMENTO)
MIMES_IMAGEM = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
MIME_PDF = 'application/pdf'
CHAVE_REGISTRO = 'comprovante_parcela'
OBSERVACAO_COMPROVANTE = 'Enviado pelo cliente no WhatsApp.'


class AnexoIndisponivel(Exception):
    """Mensagem pronta para o modelo."""


def _mime(midia: Midia) -> str:
    return (midia.mime or '').split(';')[0].strip().lower()


def _ler(midia: Midia) -> bytes:
    with midia.arquivo.open('rb') as arquivo:
        return arquivo.read()


def _anexos_recentes(conversa: Conversa, janela: timedelta):
    return (Mensagem.objects
            .filter(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA, tipo__in=TIPOS_ANEXO,
                    criado_em__gte=timezone.now() - janela, midia__status=Midia.Status.OK)
            .select_related('midia').order_by('-criado_em', '-id'))


def blocos_de_visao(mensagem: Mensagem) -> list[dict]:
    """Bloco de imagem/PDF para o Claude ver o arquivo (vazio se não couber ou não for legível)."""
    midia = getattr(mensagem, 'midia', None)
    if midia is None or midia.status != Midia.Status.OK or not midia.arquivo:
        return []
    mime = _mime(midia)
    if mime not in MIMES_IMAGEM and mime != MIME_PDF:
        return []
    if (midia.tamanho_bytes or 0) > MAX_BYTES_VISAO:
        return []
    try:
        conteudo = _ler(midia)
    except OSError:
        logger.warning('Mídia %s indisponível no storage para o assistente.', midia.pk)
        return []
    if len(conteudo) > MAX_BYTES_VISAO:  # tamanho_bytes pode estar vazio
        return []
    dados = base64.standard_b64encode(conteudo).decode()
    tipo = 'document' if mime == MIME_PDF else 'image'
    return [{'type': tipo, 'source': {'type': 'base64', 'media_type': mime, 'data': dados}}]


def ids_visiveis(conversa: Conversa) -> set[int]:
    """Os anexos mais recentes que o assistente pode ver neste turno."""
    recentes = _anexos_recentes(conversa, JANELA_VISAO)[:MAX_ANEXOS_VISTOS]
    return {m.pk for m in recentes}


def registrar_comprovante(conversa: Conversa, parcela) -> Mensagem:
    """Anexa o último arquivo do cliente (ainda não usado) à parcela e marca 'pagamento informado'."""
    from vendas.models import ComprovanteParcela

    mensagem = next((m for m in _anexos_recentes(conversa, JANELA_COMPROVANTE)
                     if not (m.dados or {}).get(CHAVE_REGISTRO)), None)
    if mensagem is None:
        raise AnexoIndisponivel('Não há imagem ou PDF recente do cliente nesta conversa (ou ele já foi anexado). '
                                'Peça para o cliente mandar o comprovante aqui.')
    midia = mensagem.midia
    extensao = os.path.splitext(midia.arquivo.name)[1].lstrip('.').lower()
    if extensao not in ComprovanteParcela.EXTENSOES_PERMITIDAS:
        raise AnexoIndisponivel('Esse arquivo não é imagem nem PDF. Peça o comprovante em foto ou PDF.')
    try:
        conteudo = _ler(midia)
    except OSError as erro:
        raise AnexoIndisponivel('O arquivo ainda não está disponível. Transfira para a equipe conferir.') from erro
    with transaction.atomic():
        # Trava mensagem e parcela: reentrega do webhook não anexa o mesmo arquivo duas vezes.
        travada = Mensagem.objects.select_for_update().get(pk=mensagem.pk)
        parcela = type(parcela).objects.select_for_update().get(pk=parcela.pk)
        if (travada.dados or {}).get(CHAVE_REGISTRO) or parcela.pagamento_efetuado or parcela.pago:
            raise AnexoIndisponivel('Esse comprovante já foi registrado. Diga que a equipe está conferindo.')
        comprovante = ComprovanteParcela(parcela=parcela, observacao=OBSERVACAO_COMPROVANTE)
        comprovante.arquivo.save(f'whatsapp_{mensagem.pk}.{extensao}', ContentFile(conteudo), save=False)
        comprovante.save()
        parcela.pagamento_efetuado = True
        parcela.pagamento_efetuado_em = timezone.now()
        parcela.data_pagamento = timezone.localdate()
        parcela.save(update_fields=['pagamento_efetuado', 'pagamento_efetuado_em', 'data_pagamento',
                                    'modificado_em'])
        travada.dados = {**(travada.dados or {}), CHAVE_REGISTRO: parcela.pk}
        travada.save(update_fields=['dados'])
    return travada
