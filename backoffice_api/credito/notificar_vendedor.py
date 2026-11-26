"""Botão "Notificar vendedor": reenvia ao vendedor o aviso de venda liberada (popup de gerar venda).

Só vale quando a venda já pode ser gerada (mesmas travas de `gerar-venda`) e no máximo
uma vez a cada `INTERVALO_SEGUNDOS` por solicitação. O controle usa o `RegistroAuditoria`
(o cache padrão é por processo e não serviria com vários workers).
"""
from datetime import datetime, timedelta

from django.utils import timezone

from backoffice_api.models import RegistroAuditoria
from vendas.services import ErroDeNegocio
from vendas.services.venda import validar_analise_para_venda

ACAO_AUDITORIA = 'vendedor_notificado'
INTERVALO_SEGUNDOS = 30


def ultimo_aviso(analise) -> datetime | None:
    """Quando o vendedor foi notificado pela última vez por este botão."""
    return (
        RegistroAuditoria.objects.filter(
            acao=ACAO_AUDITORIA, objeto_tipo=analise._meta.label_lower, objeto_id=str(analise.pk),
        )
        .order_by('-criado_em')
        .values_list('criado_em', flat=True)
        .first()
    )


def segundos_para_novo_aviso(analise, agora: datetime | None = None) -> int:
    """0 = pode notificar agora."""
    ultimo = ultimo_aviso(analise)
    if ultimo is None:
        return 0
    restante = (ultimo + timedelta(seconds=INTERVALO_SEGUNDOS)) - (agora or timezone.now())
    return max(0, int(restante.total_seconds() + 0.999))


def validar_pode_notificar(analise) -> None:
    """Há vendedor e a venda pode ser gerada; senão `ErroDeNegocio` com o motivo."""
    if analise.criado_por_id is None:
        raise ErroDeNegocio('Esta solicitação não tem vendedor para notificar.')
    validar_analise_para_venda(analise, bloquear_imei_de_venda_cancelada=False)


def pode_notificar(analise) -> bool:
    try:
        validar_pode_notificar(analise)
    except ErroDeNegocio:
        return False
    return True


def mensagem_do_aviso(analise) -> tuple[str, str]:
    nome = (analise.cliente.nome or 'Cliente').strip().title()
    loja = (analise.loja.nome if analise.loja else '').strip().title()
    verb = f'A venda de {nome} está liberada. Gere a venda agora.'
    return verb, f'Loja {loja}.' if loja else ''
