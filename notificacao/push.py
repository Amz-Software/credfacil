"""Web Push: avisa o vendedor no celular mesmo com a tela do sistema fechada.

Liga com as chaves VAPID no ambiente (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`,
`VAPID_CONTATO`); sem elas o push fica desligado e nada muda. Gerar as chaves:
`python manage.py gerar_chaves_vapid`.

Como o WebSocket, o envio é best-effort: só depois do commit, numa thread de fundo,
com timeout, e nunca derruba o request. Só os eventos que pedem ação do vendedor
(`EVENTOS_PUSH`) viram push; o resto continua só no sino.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)

EVENTOS_PUSH = {
    'proposta_aceita': 'Proposta aprovada',
    'proposta_negada': 'Proposta reprovada',
    'proposta_cancelada': 'Solicitação cancelada',
    'instalacao_confirmada': 'Venda liberada',
    'venda_liberada': 'Venda liberada',
    'pre_analise_aprovada': 'Análise rápida aprovada',
    'pre_analise_reprovada': 'Análise rápida reprovada',
}
TIMEOUT_SEGUNDOS = 5
VALIDADE_SEGUNDOS = 12 * 60 * 60  # TTL: aparelho desligado recebe ao ligar, até 12 h depois
ENDPOINT_EXPIRADO = (404, 410)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='notificacao-push')


def chave_publica() -> str:
    return getattr(settings, 'VAPID_PUBLIC_KEY', '') or ''


def ativo() -> bool:
    return bool(chave_publica() and getattr(settings, 'VAPID_PRIVATE_KEY', ''))


def montar_carga(event: str, verb: str, description: str, target_url: str) -> dict:
    """O que o service worker mostra: título curto pelo evento, texto e para onde o toque leva."""
    return {
        'titulo': EVENTOS_PUSH.get(event, 'IPX'),
        'corpo': verb if not description else f'{verb} {description}',
        'url': target_url or '/app',
        'tag': f'{event}:{target_url}',
    }


def _enviar_para(assinatura, carga: dict) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={'endpoint': assinatura.endpoint, 'keys': {'p256dh': assinatura.p256dh, 'auth': assinatura.auth}},
            data=json.dumps(carga),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': getattr(settings, 'VAPID_CONTATO', '') or 'mailto:suporte@centralipx.com'},
            ttl=VALIDADE_SEGUNDOS,
            timeout=TIMEOUT_SEGUNDOS,
        )
    except WebPushException as erro:
        status = getattr(getattr(erro, 'response', None), 'status_code', None)
        if status in ENDPOINT_EXPIRADO:
            assinatura.delete()  # aparelho desinscrito ou app removido
            return
        logger.warning('Push recusado para a assinatura %s (HTTP %s).', assinatura.pk, status)
    except Exception:  # noqa: BLE001 — push é best-effort
        logger.warning('Falha ao enviar push para a assinatura %s.', assinatura.pk, exc_info=True)


def enviar_agora(usuario_id: int, carga: dict) -> int:
    """Envia para todos os aparelhos do usuário. Devolve quantas assinaturas foram tentadas."""
    from notificacao.models import AssinaturaPush

    assinaturas = list(AssinaturaPush.objects.filter(usuario_id=usuario_id))
    for assinatura in assinaturas:
        _enviar_para(assinatura, carga)
    return len(assinaturas)


def _em_segundo_plano(usuario_id: int, carga: dict) -> None:
    close_old_connections()
    try:
        enviar_agora(usuario_id, carga)
    finally:
        close_old_connections()


def agendar(usuario_id: int, event: str | None, verb: str, description: str, target_url: str) -> None:
    """Agenda o push (depois do commit) se o evento pede ação do vendedor e o push está ligado."""
    if not event or event not in EVENTOS_PUSH or not ativo():
        return
    carga = montar_carga(event, verb, description, target_url)

    def disparar():
        if getattr(settings, 'NOTIFICACAO_WS_SINCRONO', False):
            enviar_agora(usuario_id, carga)
            return
        try:
            _executor.submit(_em_segundo_plano, usuario_id, carga)
        except RuntimeError:
            logger.warning('Push para o usuário %s descartado: servidor desligando.', usuario_id)

    transaction.on_commit(disparar)
