"""Envio dos disparos manuais confirmados (rotina do worker, a cada minuto).

Regras: no máximo ENVIOS_POR_MINUTO por minuto (somando todos os disparos), só na janela de envio
(não em domingo/feriado), nunca para número de referência, ninguém que recebeu aviso nas últimas 48 h,
dentro do teto das últimas 24 h menos o que a régua ainda vai mandar hoje (o resto continua depois),
nada com o número pausado (qualidade ou Meta sem resposta), pausa o disparo depois de MAX_FALHAS_SEGUIDAS
recusas seguidas da Meta ou se a mensagem mudou, e expira o que não saiu 3 dias depois da confirmação.

Cada item é reservado (PENDENTE → ENVIANDO, só um processo consegue) antes de enviar; o teto é conferido
de novo dentro da transação do envio (`teto.reservar_vaga`).
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import caches
from django.db.models import F
from django.utils import timezone

from crm.models import ConfiguracaoCRM, DisparoCobranca, ItemDisparo, TentativaContato
from crm.services import cobranca

from . import agenda, janela
from .disparos import (ENVIOS_POR_MINUTO, JANELA_AVISO_RECENTE, clientes_avisados_desde, expirado,
                       motivo_do_destinatario, vagas_do_disparo, versao_igual)
from .motivos import Motivo, telefone_para_aviso
from .teto import TetoAtingido, ler_saude

logger = logging.getLogger(__name__)

Status = DisparoCobranca.Status
Situacao = ItemDisparo.Situacao
Tipo = cobranca.Tipo
CHAVE_MINUTO = 'crm:cobranca:disparos_minuto'
TRAVA_SEGUNDOS = 60  # o worker roda a cada minuto: no máximo uma passada por minuto
RESERVA_ESQUECIDA = timedelta(minutes=10)  # item ENVIANDO de um processo que morreu
EXAMES_POR_ENVIO = 5  # itens ignorados não gastam vaga, mas cada minuto examina no máximo 5x as vagas
MOTIVO_PAUSA_META = 'A Meta recusou {n} envios seguidos ({detalhe}). Confira o template e o número e retome.'
MOTIVO_PAUSA_MODELO = 'A mensagem mudou ou deixou de estar aprovada pela Meta depois da prévia. Crie um novo disparo.'
CONTADORES = {Situacao.ENVIADO: 'enviados', Situacao.FALHOU: 'falhas', Situacao.IGNORADO: 'ignorados'}


def _reservar_minuto() -> bool:
    try:
        return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')].add(CHAVE_MINUTO, 1, TRAVA_SEGUNDOS)
    except Exception:  # noqa: BLE001 — sem Redis: a reserva de cada item e a trava do teto evitam excesso
        logger.warning('Cache compartilhado indisponível; disparos sem trava de minuto.', exc_info=True)
        return True


def _ativo(disparo: DisparoCobranca) -> bool:
    return DisparoCobranca.objects.filter(pk=disparo.pk, status__in=DisparoCobranca.EM_ANDAMENTO).exists()


def _pausar(disparo: DisparoCobranca, motivo: str) -> None:
    """Só pausa o que ainda está em andamento (nunca desfaz um cancelamento)."""
    DisparoCobranca.objects.filter(pk=disparo.pk, status__in=DisparoCobranca.EM_ANDAMENTO).update(
        status=Status.PAUSADO, motivo_pausa=motivo[:255], atualizado_em=timezone.now())


def _reservar_item(item: ItemDisparo) -> bool:
    return ItemDisparo.objects.filter(pk=item.pk, situacao=Situacao.PENDENTE).update(
        situacao=Situacao.ENVIANDO, processado_em=timezone.now()) == 1


def _devolver_item(item: ItemDisparo) -> None:
    ItemDisparo.objects.filter(pk=item.pk, situacao=Situacao.ENVIANDO).update(situacao=Situacao.PENDENTE,
                                                                          processado_em=None)


def _registrar(item: ItemDisparo, situacao: str, motivo: str = '', tentativa=None) -> None:
    ItemDisparo.objects.filter(pk=item.pk).update(situacao=situacao, motivo=motivo, tentativa=tentativa,
                                                  processado_em=timezone.now())
    contador = CONTADORES[situacao]
    campos = {contador: F(contador) + 1, 'atualizado_em': timezone.now()}
    if situacao != Situacao.IGNORADO:
        campos['falhas_seguidas'] = F('falhas_seguidas') + 1 if situacao == Situacao.FALHOU else 0
    DisparoCobranca.objects.filter(pk=item.disparo_id).update(**campos)


def recuperar_reservas_esquecidas(agora: datetime | None = None) -> int:
    """Itens ENVIANDO de um processo que morreu: se a mensagem saiu, ENVIADO; senão voltam para a fila."""
    limite = (agora or timezone.now()) - RESERVA_ESQUECIDA
    total = 0
    for item in ItemDisparo.objects.filter(situacao=Situacao.ENVIANDO, processado_em__lt=limite):
        tentativa = TentativaContato.objects.filter(parcela_id=item.parcela_id, tipo=Tipo.DISPARO,
                                                    sequencia=item.disparo_id).first()
        if tentativa is not None:
            _registrar(item, Situacao.ENVIADO, tentativa=tentativa)
        else:
            _devolver_item(item)
        total += 1
    return total


def _parcela_atual(item: ItemDisparo):
    from vendas.models import Parcela

    if item.parcela_id is None:
        return None
    return (Parcela.objects.filter(pk=item.parcela_id)
            .select_related('pagamento__venda__cliente__contato_adicional',
                            'pagamento__venda__cliente__informacao_pessoal').first())


def _motivo_antes_de_enviar(item: ItemDisparo, local: datetime) -> tuple[object, str]:
    """(parcela, motivo para ignorar). Mesma regra da prévia (`motivo_do_destinatario`)."""
    parcela = _parcela_atual(item)
    aberta = parcela is not None and cobranca._parcelas_abertas().filter(pk=parcela.pk).exists()
    if parcela is None or (not aberta and not parcela.pago and not parcela.pagamento_efetuado):
        return parcela, Motivo.PARCELA_INDISPONIVEL
    recentes = clientes_avisados_desde([item.cliente_id], local - JANELA_AVISO_RECENTE)
    return parcela, motivo_do_destinatario(parcela, recentes)


def _motivo_sem_envio(parcela, local: datetime) -> str:
    """`enviar_aviso` não enviou: por quê (telefone sumiu, aviso recente de outra rotina ou texto inválido)."""
    cliente = parcela.pagamento.venda.cliente
    motivo_telefone = telefone_para_aviso(cliente)[1]
    if motivo_telefone:
        return motivo_telefone
    if clientes_avisados_desde([cliente.pk], local - JANELA_AVISO_RECENTE):
        return Motivo.AVISO_RECENTE
    return Motivo.NAO_ENVIADO


def _enviar_item(disparo: DisparoCobranca, item: ItemDisparo, local: datetime, limite: int) -> tuple[str, str]:
    """Confere o item reservado e envia. Devolve (situação final, detalhe da recusa da Meta).

    Teto atingido no meio: o item volta para a fila e levanta `TetoAtingido`.
    """
    parcela, motivo = _motivo_antes_de_enviar(item, local)
    if motivo:
        _registrar(item, Situacao.IGNORADO, motivo)
        return Situacao.IGNORADO, ''
    try:
        mensagem = cobranca.enviar_aviso(disparo.versao, parcela, Tipo.DISPARO, disparo.pk, local.date(),
                                         local - JANELA_AVISO_RECENTE, limite=limite)
    except TetoAtingido:
        _devolver_item(item)
        raise
    except cobranca.FalhaDeEnvio as erro:
        logger.warning('Meta recusou o disparo %s da parcela %s: %s', disparo.pk, parcela.pk, erro)
        _registrar(item, Situacao.FALHOU, Motivo.RECUSADO_PELA_META)
        return Situacao.FALHOU, str(erro)
    if mensagem is None:
        _registrar(item, Situacao.IGNORADO, _motivo_sem_envio(parcela, local))
        return Situacao.IGNORADO, ''
    _registrar(item, Situacao.ENVIADO, tentativa=mensagem.tentativas.first())
    return Situacao.ENVIADO, ''


def _iniciar(disparo: DisparoCobranca) -> None:
    if disparo.status == Status.AGENDADO:
        DisparoCobranca.objects.filter(pk=disparo.pk, status=Status.AGENDADO).update(
            status=Status.ENVIANDO, iniciado_em=timezone.now(), atualizado_em=timezone.now())


def _concluir_se_acabou(disparo: DisparoCobranca) -> None:
    if not disparo.itens.filter(situacao__in=(Situacao.PENDENTE, Situacao.ENVIANDO)).exists():
        DisparoCobranca.objects.filter(pk=disparo.pk, status__in=DisparoCobranca.EM_ANDAMENTO).update(
            status=Status.CONCLUIDO, concluido_em=timezone.now(), atualizado_em=timezone.now())


def _expirar(disparo: DisparoCobranca) -> None:
    """Confirmado há mais de IDADE_MAXIMA: o que não saiu não sai mais (texto e valores ficaram velhos)."""
    pendentes = disparo.itens.filter(situacao=Situacao.PENDENTE)
    quantidade = pendentes.update(situacao=Situacao.IGNORADO, motivo=Motivo.DISPARO_EXPIRADO,
                                  processado_em=timezone.now())
    DisparoCobranca.objects.filter(pk=disparo.pk).update(ignorados=F('ignorados') + quantidade,
                                                         atualizado_em=timezone.now())
    _concluir_se_acabou(disparo)


def _processar_disparo(disparo: DisparoCobranca, vagas: int, local: datetime, limite: int) -> int:
    """Envia até `vagas` itens do disparo; devolve quantos saíram."""
    if expirado(disparo, local):
        _expirar(disparo)
        return 0
    if not versao_igual(disparo):  # template trocado, pausado ou desativado depois da prévia
        _pausar(disparo, MOTIVO_PAUSA_MODELO)
        return 0
    _iniciar(disparo)
    enviados, seguidas = 0, disparo.falhas_seguidas
    pendentes = list(disparo.itens.filter(situacao=Situacao.PENDENTE).order_by('ordem')[:vagas * EXAMES_POR_ENVIO])
    for item in pendentes:
        if enviados >= vagas or not _ativo(disparo):
            break
        if not _reservar_item(item):
            continue  # outro processo pegou este item
        try:
            situacao, detalhe = _enviar_item(disparo, item, local, limite)
        except TetoAtingido:
            return enviados
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
    recuperar_reservas_esquecidas(local)
    saude = ler_saude(config)
    if saude.pausada:
        logger.warning('Disparos pausados (%s); qualidade %s.', saude.motivo_pausa, saude.qualidade)
        return {}
    reserva_hoje = agenda.reserva_da_regua(config, saude, local).get(local.date(), 0)
    limite = max(saude.teto_efetivo - reserva_hoje, 0)  # a vaga da régua de hoje não é do disparo
    vagas = min(ENVIOS_POR_MINUTO, vagas_do_disparo(saude, reserva_hoje, local))
    resultado = {}
    for disparo in em_andamento:
        if vagas <= 0 and not expirado(disparo, local):
            continue  # sem vaga agora; os expirados ainda são encerrados
        enviados = _processar_disparo(disparo, vagas, local, limite)
        vagas -= enviados
        resultado[disparo.pk] = enviados
    return resultado
