"""O que o usuário pode fazer agora com a solicitação (a SPA usa para mostrar os botões).

É só conforto de interface: cada endpoint confere de novo a permissão e a regra.
"""
from vendas.models import AnaliseCreditoCliente
from vendas.services import ErroDeNegocio
from vendas.services import analise as servico_analise

from .notificar_vendedor import pode_notificar
from .regras import (
    APP_CONFIRMACAO_PENDENTE,
    PERMISSAO_DECIDIR,
    STATUS_APROVADO,
    STATUS_CANCELADO,
    STATUS_REPROVADO,
    eh_analista,
    pode_editar_apos_venda,
    pode_observar,
    pode_ver_serasa,
)


def _pode_informar_imei(analise: AnaliseCreditoCliente) -> bool:
    try:
        servico_analise.validar_pode_informar_imei(analise)
    except ErroDeNegocio:
        return False
    return True


def acoes_disponiveis(user, analise: AnaliseCreditoCliente) -> dict[str, bool]:
    decide = user.has_perm(PERMISSAO_DECIDIR)
    analista = eh_analista(user)
    venda_gerada = analise.venda_id is not None
    iphone = analise.produto.is_iphone
    return {
        'editar': user.has_perm('vendas.change_cliente') and (not venda_gerada or pode_editar_apos_venda(user)),
        'aprovar': decide and analise.status != STATUS_APROVADO,
        'reprovar': decide and analise.status != STATUS_REPROVADO,
        'cancelar': (
            decide and user.has_perm('vendas.change_analisecreditocliente') and analise.status != STATUS_CANCELADO
        ),
        'observar': pode_observar(user),
        'alterar_status_app': user.has_perm('vendas.change_cliente'),
        'instalar_app': user.has_perm('vendas.change_cliente') and not iphone,
        'confirmar_instalacao': (
            decide and analista and not iphone and bool(analise.imei_id)
            and analise.status_aplicativo == APP_CONFIRMACAO_PENDENTE
        ),
        'confirmar_icloud': (
            decide and analista and iphone and analise.icloud_configurado_vendedor
            and not analise.icloud_confirmado_analista
        ),
        'informar_imei': (
            user.has_perm('vendas.change_analisecreditocliente') and analista and _pode_informar_imei(analise)
        ),
        'gerar_venda': user.has_perm('vendas.add_venda') and analise.status == STATUS_APROVADO and not venda_gerada,
        'notificar_vendedor': decide and analise.status == STATUS_APROVADO and not venda_gerada and pode_notificar(analise),
        'ver_serasa': pode_ver_serasa(user),
    }
