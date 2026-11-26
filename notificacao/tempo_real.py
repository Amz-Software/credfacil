"""Aviso em tempo real de que uma solicitação mudou (SPA do vendedor recarrega pela API).

Diferente das notificações do sino, o evento não cria `Notification` nem abre
modal: só leva o id do cliente para a tela refazer as consultas. Assim todo o
fluxo de geração da venda (aprovação, IMEI, instalação, iCloud, venda) aparece
sem o vendedor atualizar a página.
"""
import logging

from django.db.models import Q

from accounts.models import User
from notificacao.utils import enviar_evento_ws

logger = logging.getLogger(__name__)

EVENTO_SOLICITACAO_ATUALIZADA = 'solicitacao_atualizada'


def destinatarios_da_solicitacao(cliente) -> set[int]:
    """Quem acompanha a solicitação pela SPA: quem criou e os usuários/gerentes da loja."""
    ids: set[int] = set()
    if cliente.criado_por_id:
        ids.add(cliente.criado_por_id)
    if cliente.loja_id:
        ids.update(
            User.objects.filter(
                Q(loja=cliente.loja_id) | Q(lojas=cliente.loja_id) | Q(lojas_gerenciadas=cliente.loja_id)
            )
            .values_list('id', flat=True)
            .distinct()
        )
    return ids


def avisar_solicitacao_atualizada(cliente, *, criado_por_id: int | None = None) -> None:
    """Agenda o evento (depois do commit) para cada destinatário. Nunca levanta erro."""
    try:
        ids = destinatarios_da_solicitacao(cliente)
        if criado_por_id:
            ids.add(criado_por_id)
        mensagem = {'type': EVENTO_SOLICITACAO_ATUALIZADA, 'cliente_id': cliente.pk}
        for usuario_id in ids:
            enviar_evento_ws(usuario_id, mensagem)
    except Exception:  # noqa: BLE001 — tempo real é best-effort, não derruba o save
        logger.warning('Falha ao agendar o aviso de solicitação %s atualizada.', cliente.pk, exc_info=True)
