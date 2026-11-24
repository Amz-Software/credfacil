"""Depois da baixa: avisa a equipe (sino) e confirma ao cliente no WhatsApp, se a janela de 24h estiver aberta."""
import logging

from django.urls import reverse

from vendas.services.notificacoes import GRUPOS_ANALISE, notificar_grupos

from crm.services.pagamentos import formatar_reais as reais

from ..models import Cobranca

logger = logging.getLogger(__name__)

TIPO_NOTIFICACAO = 'pagamento_online'


def _texto_equipe(cobranca: Cobranca) -> str:
    cliente = cobranca.parcela.pagamento.venda.cliente
    texto = (f'{cliente.nome} pagou a parcela {cobranca.parcela.numero_parcela} '
             f'({reais(cobranca.valor_parcela)}) via {cobranca.get_forma_display()}.')
    if cobranca.acerto_manual:
        texto += f' Atenção, precisa de acerto: {cobranca.acerto_manual}'
    return texto


def _avisar_equipe(cobranca: Cobranca) -> None:
    pagamento = cobranca.parcela.pagamento
    notificar_grupos(
        grupos=GRUPOS_ANALISE, autor=None, instance=cobranca.parcela, target=pagamento,
        verb='Pagamento recebido pelo PagBank', description=_texto_equipe(cobranca),
        target_url=reverse('financeiro:contas_a_receber_update', kwargs={'pk': pagamento.pk}),
        type_notification=TIPO_NOTIFICACAO,
    )


def _texto_cliente(cobranca: Cobranca) -> str:
    primeiro_nome = (cobranca.parcela.pagamento.venda.cliente.nome or '').split(' ')[0]
    return (f'Oi, {primeiro_nome}! Recebemos o pagamento da parcela {cobranca.parcela.numero_parcela} '
            f'({reais(cobranca.valor_total)}). Obrigado! O comprovante fica disponível na sua área de pagamentos.')


def _avisar_cliente(cobranca: Cobranca) -> bool:
    from crm.models import Mensagem
    from crm.services import envio

    cliente = cobranca.parcela.pagamento.venda.cliente
    conversa = next((c for c in cliente.conversas_whatsapp.all() if c.janela_aberta()), None)
    if conversa is None:
        return False
    envio.enviar_texto(conversa, _texto_cliente(cobranca), usuario=None, autor=Mensagem.Autor.AUTOMATICO,
                       origem='pagamento_online', exigir_trava=False)
    return True


def avisar_pagamento(cobranca_id: int) -> None:
    cobranca = Cobranca.objects.select_related('parcela__pagamento__venda__cliente').get(pk=cobranca_id)
    for etapa in (_avisar_equipe, _avisar_cliente):
        try:
            etapa(cobranca)
        except Exception:  # noqa: BLE001 — um aviso com falha não desfaz a baixa
            logger.exception('Falha no aviso %s da cobrança %s.', etapa.__name__, cobranca_id)
