"""Regras de acesso e de situação das vendas no backoffice (sem efeitos colaterais)."""
from accounts.permissions import user_is_analista_or_admin
from vendas.services.erros import PROIBIDO, ErroDeNegocio

CAMPOS_DOCUMENTO = {
    'documento_assinado': 'Documento assinado',
    'foto_cliente': 'Foto do cliente',
    'imagem_imei': 'Imagem do IMEI',
}
PERMISSAO_EDITAR_FINALIZADA = 'vendas.can_edit_finished_sale'
TIPO_ENTRADA = 'ENTRADA'


def situacao_da_venda(venda) -> str:
    if venda.is_deleted:
        return 'cancelada'
    if venda.is_trocado:
        return 'trocada'
    return 'ativa'


def veio_de_analise(venda) -> bool:
    """Venda gerada por uma análise de crédito ("venda finalizada" da solicitação)."""
    anotado = getattr(venda, 'veio_de_analise', None)
    if anotado is not None:
        return bool(anotado)
    return venda.analises_credito_venda.exists()


def pode_editar_venda_finalizada(user) -> bool:
    """Mesma regra das telas: ANALISTA/ADMINISTRADOR ou `can_edit_finished_sale`."""
    return user_is_analista_or_admin(user) or user.has_perm(PERMISSAO_EDITAR_FINALIZADA)


def garantir_venda_ativa(venda) -> None:
    if venda.is_deleted:
        raise ErroDeNegocio('Esta venda está cancelada e não pode ser alterada.')


def garantir_pode_editar(venda, user) -> None:
    garantir_venda_ativa(venda)
    if veio_de_analise(venda) and not pode_editar_venda_finalizada(user):
        raise ErroDeNegocio(
            'Esta venda foi gerada por uma análise de crédito. Só ANALISTA, ADMINISTRADOR ou quem '
            'pode editar venda finalizada consegue alterá-la.',
            codigo=PROIBIDO,
        )


def eh_entrada(pagamento) -> bool:
    return bool(pagamento.tipo_pagamento and pagamento.tipo_pagamento.nome.upper() == TIPO_ENTRADA)


def pagamento_carne(venda):
    """Primeiro pagamento em carnê/promissória (usa o prefetch quando houver)."""
    if 'pagamentos' in getattr(venda, '_prefetched_objects_cache', {}):
        return next((p for p in venda.pagamentos.all() if p.tipo_pagamento.carne), None)
    return (
        venda.pagamentos.select_related('tipo_pagamento')
        .filter(tipo_pagamento__carne=True)
        .order_by('pk')
        .first()
    )


def acoes_disponiveis(venda, user) -> dict:
    """O que o usuário pode fazer nesta venda (só conforto para a SPA; o servidor confere de novo)."""
    ativa = not venda.is_deleted
    pode_alterar = ativa and user.has_perm('vendas.change_venda')
    return {
        'editar': pode_alterar and (not veio_de_analise(venda) or pode_editar_venda_finalizada(user)),
        'edicao_especial': ativa and user.has_perm('vendas.can_edit_imei_valores_venda'),
        'trocar_produto': pode_alterar,
        'cancelar': ativa and user.has_perm('vendas.delete_venda'),
        'enviar_documentos': pode_alterar,
    }
