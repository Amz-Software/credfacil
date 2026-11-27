"""Envio dos disparos manuais confirmados (rotina do worker, a cada minuto).

Regras: no máximo ENVIOS_POR_MINUTO por minuto (somando todos os disparos), só na janela de envio
(não em domingo/feriado), nunca para número de referência, ninguém que recebeu aviso nas últimas 48 h,
dentro do teto diário (o que sobra continua no próximo dia de envio), nada com o número pausado pela
qualidade, e pausa o disparo depois de MAX_FALHAS_SEGUIDAS recusas seguidas da Meta (retomar pela API).
"""
import logging
from datetime import datetime

from django.conf import settings
from django.core.cache import caches
from django.db.models import F
from django.utils import timezone

from crm.models import ConfiguracaoCRM, DisparoCobranca, ItemDisparo
from crm.services import cobranca
from crm.services.conversas import ConflitoCRM

from . import janela
from .disparos import (ENVIOS_POR_MINUTO, JANELA_AVISO_RECENTE, clientes_avisados_desde, motivo_do_destinatario,
                       versao_para_disparo)
from .motivos import Motivo
from .teto import ler_saude, restante_no_dia

logger = logging.getLogger(__name__)

Status = DisparoCobranca.Status
Situacao = ItemDisparo.Situacao
Tipo = cobranca.Tipo
CHAVE_MINUTO = 'crm:cobranca:disparos_minuto'
TRAVA_SEGUNDOS = 50
EXAMES_POR_ENVIO = 5  # itens ignorados não gastam vaga, mas cada minuto examina no máximo 5x as vagas
MOTIVO_PAUSA_META = 'A Meta recusou {n} envios seguidos ({detalhe}). Confira o template e o número e retome.'
MOTIVO_PAUSA_MODELO = 'A mensagem deixou de estar aprovada pela Meta. Retome quando ela voltar a valer.'


def _reservar_minuto() -> bool:
    try:
        return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')].add(CHAVE_MINUTO, 1, TRAVA_SEGUNDOS)
    except Exception:  # noqa: BLE001 — sem Redis, a trava do cliente no banco ainda evita envio duplicado
        logger.warning('Cache compartilhado indisponível; disparos sem trava de minuto.', exc_info=True)
        return True


def _ativo(disparo: DisparoCobranca) -> bool:
    return DisparoCobranca.objects.filter(pk=disparo.pk, status__in=DisparoCobranca.EM_ANDAMENTO).exists()


def _pausar(disparo: DisparoCobranca, motivo: str) -> None:
    DisparoCobranca.objects.filter(pk=disparo.pk).update(status=Status.PAUSADO, motivo_pausa=motivo[:255],
                                                         atualizado_em=timezone.now())


def _registrar(item: ItemDisparo, situacao: str, motivo: str = '', tentativa=None) -> None:
    ItemDisparo.objects.filter(pk=item.pk).update(situacao=situacao, motivo=motivo, tentativa=tentativa,
                                                  processado_em=timezone.now())
    contador = {Situacao.ENVIADO: 'enviados', Situacao.FALHOU: 'falhas', Situacao.IGNORADO: 'ignorados'}[situacao]
    seguidas = F('falhas_seguidas') + 1 if situacao == Situacao.FALHOU else 0
    campos = {contador: F(contador) + 1, 'atualizado_em': timezone.now()}
    if situacao != Situacao.IGNORADO:
        campos['falhas_seguidas'] = seguidas
    DisparoCobranca.objects.filter(pk=item.disparo_id).update(**campos)


def _parcela_atual(item: ItemDisparo):
    from vendas.models import Parcela

    if item.parcela_id is None:
        return None
    return (Parcela.objects.filter(pk=item.parcela_id)
            .select_related('pagamento__venda__cliente__contato_adicional',
                            'pagamento__venda__cliente__informacao_pessoal').first())


def _enviar_item(disparo: DisparoCobranca, item: ItemDisparo, local: datetime) -> tuple[str, str]:
    """Confere o item de novo e envia. Devolve (situação final do item, detalhe da recusa da Meta)."""
    parcela = _parcela_atual(item)
    aberta = parcela is not None and cobranca._parcelas_abertas().filter(pk=parcela.pk).exists()
    if parcela is None or (not aberta and not parcela.pago and not parcela.pagamento_efetuado):
        _registrar(item, Situacao.IGNORADO, Motivo.PARCELA_INDISPONIVEL)
        return Situacao.IGNORADO, ''
    desde = local - JANELA_AVISO_RECENTE
    motivo = motivo_do_destinatario(parcela, clientes_avisados_desde([item.cliente_id], desde))
    if motivo:
        _registrar(item, Situacao.IGNORADO, motivo)
        return Situacao.IGNORADO, ''
    try:
        mensagem = cobranca.enviar_aviso(disparo.versao, parcela, Tipo.DISPARO, disparo.pk, local.date(), desde)
    except cobranca.FalhaDeEnvio as erro:
        logger.warning('Meta recusou o disparo %s da parcela %s: %s', disparo.pk, parcela.pk, erro)
        _registrar(item, Situacao.FALHOU, Motivo.RECUSADO_PELA_META)
        return Situacao.FALHOU, str(erro)
    if mensagem is None:  # outra rotina avisou o cliente agora há pouco
        _registrar(item, Situacao.IGNORADO, Motivo.AVISO_RECENTE)
        return Situacao.IGNORADO, ''
    _registrar(item, Situacao.ENVIADO, tentativa=mensagem.tentativas.first())
    return Situacao.ENVIADO, ''


def _iniciar(disparo: DisparoCobranca) -> None:
    if disparo.status == Status.AGENDADO:
        DisparoCobranca.objects.filter(pk=disparo.pk, status=Status.AGENDADO).update(
            status=Status.ENVIANDO, iniciado_em=timezone.now(), atualizado_em=timezone.now())


def _concluir_se_acabou(disparo: DisparoCobranca) -> None:
    if not disparo.itens.filter(situacao=Situacao.PENDENTE).exists():
        DisparoCobranca.objects.filter(pk=disparo.pk, status__in=DisparoCobranca.EM_ANDAMENTO).update(
            status=Status.CONCLUIDO, concluido_em=timezone.now(), atualizado_em=timezone.now())


def _processar_disparo(disparo: DisparoCobranca, vagas: int, local: datetime) -> int:
    """Envia até `vagas` itens do disparo; devolve quantos saíram."""
    try:
        versao_para_disparo(disparo.modelo)
    except ConflitoCRM:  # template pausado, desativado ou trocado na Meta
        _pausar(disparo, MOTIVO_PAUSA_MODELO)
        return 0
    _iniciar(disparo)
    enviados, seguidas = 0, disparo.falhas_seguidas
    pendentes = list(disparo.itens.filter(situacao=Situacao.PENDENTE).order_by('ordem')[:vagas * EXAMES_POR_ENVIO])
    for item in pendentes:
        if enviados >= vagas or not _ativo(disparo):
            break
        situacao, detalhe = _enviar_item(disparo, item, local)
        enviados += situacao == Situacao.ENVIADO
        seguidas = seguidas + 1 if situacao == Situacao.FALHOU else (0 if situacao == Situacao.ENVIADO else seguidas)
        if seguidas >= cobranca.MAX_FALHAS_SEGUIDAS:
            _pausar(disparo, MOTIVO_PAUSA_META.format(n=seguidas, detalhe=detalhe or 'sem detalhe'))
            return enviados
    _concluir_se_acabou(disparo)
    return enviados


def processar(agora: datetime | None = None, forcar: bool = False) -> dict:
    """Chamado pela rotina do worker a cada minuto. Devolve {id do disparo: enviados}.

    `forcar` ignora a trava de um processamento por minuto (testes e comando manual).
    """
    config = ConfiguracaoCRM.obter()
    local = timezone.localtime(agora or timezone.now())
    if not janela.aberta(config, local):
        return {}
    em_andamento = list(DisparoCobranca.objects.filter(status__in=DisparoCobranca.EM_ANDAMENTO)
                        .select_related('modelo', 'versao').order_by('confirmado_em', 'pk'))
    if not em_andamento or not (forcar or _reservar_minuto()):
        return {}
    saude = ler_saude(config)
    if saude.pausada_por_qualidade:
        logger.warning('Disparos pausados: qualidade %s do número na Meta.', saude.qualidade)
        return {}
    vagas = min(ENVIOS_POR_MINUTO, restante_no_dia(saude, local.date()))
    resultado = {}
    for disparo in em_andamento:
        if vagas <= 0:
            break
        enviados = _processar_disparo(disparo, vagas, local)
        vagas -= enviados
        resultado[disparo.pk] = enviados
    return resultado
