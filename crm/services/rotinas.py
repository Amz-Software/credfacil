"""Rotinas periódicas do CRM (serviço crm-worker / comando crm_rotinas)."""
import logging
from datetime import timedelta

from django.utils import timezone

from crm.models import Conversa, Mensagem, Midia
from crm.services import aberturas, chamadas, cobranca, conversas, midias, organizacao
from crm.services.central_cobranca import envio_disparos

logger = logging.getLogger(__name__)

ENVIO_TRAVADO = timedelta(minutes=10)
ENTRADA_ESQUECIDA = timedelta(minutes=2)
MIDIA_EXPIRA = timedelta(days=7)
LIMITE_MIDIAS_POR_RODADA = 50


def marcar_envios_travados() -> int:
    limite = timezone.now() - ENVIO_TRAVADO
    return Mensagem.objects.filter(
        direcao=Mensagem.Direcao.SAIDA, status=Mensagem.Status.PENDENTE, envio_iniciado_em__lt=limite,
    ).update(status=Mensagem.Status.ERRO, erro='Envio interrompido. Reenvie a mensagem.')


def processar_midias_pendentes() -> int:
    agora = timezone.now()
    Midia.objects.filter(
        status__in=[Midia.Status.PENDENTE, Midia.Status.ERRO], mensagem__criado_em__lt=agora - MIDIA_EXPIRA,
        mensagem__direcao=Mensagem.Direcao.ENTRADA,
    ).update(status=Midia.Status.EXPIRADA)
    pendentes = Midia.objects.filter(
        status__in=[Midia.Status.PENDENTE, Midia.Status.ERRO], tentativas__lt=midias.MAX_TENTATIVAS,
        mensagem__direcao=Mensagem.Direcao.ENTRADA, mensagem__processada=True,
    ).select_related('mensagem')[:LIMITE_MIDIAS_POR_RODADA]
    total = 0
    for midia in pendentes:
        try:
            midias.baixar(midia)
            midias.transcrever(midia.mensagem)
            total += 1
        except Exception:  # noqa: BLE001
            logger.exception('Falha ao baixar a mídia %s.', midia.pk)
    return total


def reprocessar_entradas() -> int:
    """Entradas que uma thread interrompida deixou sem processar."""
    limite = timezone.now() - ENTRADA_ESQUECIDA
    ids = (Mensagem.objects.filter(direcao=Mensagem.Direcao.ENTRADA, processada=False, criado_em__lt=limite)
           .values_list('conversa_id', flat=True).distinct())
    total = 0
    for conversa_id in ids:
        try:
            conversas.processar_conversa(conversa_id)
            total += 1
        except Exception:  # noqa: BLE001 — uma conversa com defeito não segura as outras
            logger.exception('Falha ao reprocessar a conversa %s.', conversa_id)
    return total


def retornar_resolvidas() -> int:
    total = 0
    candidatas = Conversa.objects.filter(situacao=Conversa.Situacao.RESOLVIDA).exclude(modo=Conversa.Modo.AUTOMATICO)
    for conversa in candidatas:
        try:
            total += int(conversas.avaliar_retorno_automatico(conversa))
        except Exception:  # noqa: BLE001
            logger.exception('Falha no retorno automático da conversa %s.', conversa.pk)
    return total


def _conciliar_pagamentos_online() -> dict:
    from pagamentos_online.servicos.conciliacao import conciliar

    return conciliar()


def rodar_tudo(incluir_aberturas: bool = True) -> dict:
    resultado = {}
    etapas = [
        ('programadas', organizacao.enviar_programadas_vencidas),
        ('programadas_travadas', organizacao.recuperar_programadas_travadas),
        ('lembretes', organizacao.avisar_lembretes_vencidos),
        ('envios_travados', marcar_envios_travados),
        ('midias', processar_midias_pendentes),
        ('entradas', reprocessar_entradas),
        ('retorno_automatico', retornar_resolvidas),
        ('cobranca', cobranca.rodar),
        ('disparos_cobranca', envio_disparos.processar),
        ('chamadas_esquecidas', chamadas.fechar_esquecidas),
        ('pagamentos_online', _conciliar_pagamentos_online),
    ]
    if incluir_aberturas:
        etapas.append(('aberturas', aberturas.sincronizar_pendentes))
    for nome, etapa in etapas:
        try:
            resultado[nome] = etapa()
        except Exception:  # noqa: BLE001 — uma etapa com erro não impede as outras
            logger.exception('Rotina do CRM falhou: %s', nome)
            resultado[nome] = 'erro'
    return resultado
