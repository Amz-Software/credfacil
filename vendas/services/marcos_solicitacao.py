"""Linha do tempo enxuta da solicitação para o vendedor (marcos do fluxo da venda).

Deriva do histórico (simple_history) da análise: só as passagens que importam
para o vendedor, sem os campos internos (Serasa, autenticador, observações).
A versão completa, campo a campo, é a do backoffice (`backoffice_api/credito/linha_do_tempo.py`).
"""
from dataclasses import asdict, dataclass
from datetime import datetime

from vendas.models import AnaliseCreditoCliente

TITULOS_STATUS = {
    'EA': 'Voltou para análise',
    'A': 'Proposta aprovada',
    'R': 'Proposta reprovada',
    'C': 'Solicitação cancelada',
}


@dataclass(frozen=True)
class Marco:
    tipo: str
    titulo: str
    data: datetime
    autor: str | None
    por_voce: bool


def _nome(usuario) -> str | None:
    if usuario is None:
        return None
    return usuario.first_name or usuario.username


def _tem_imei(registro) -> bool:
    return bool(registro.imei_id or registro.imei_informado)


def _transicoes(anterior, atual) -> list[tuple[str, str]]:
    """(tipo, título) de cada passagem entre duas versões da análise, na ordem do fluxo."""
    marcos = []
    if atual.status != anterior.status and atual.status in TITULOS_STATUS:
        marcos.append((f'status_{atual.status}', TITULOS_STATUS[atual.status]))
    if atual.icloud_configurado_vendedor and not anterior.icloud_configurado_vendedor:
        marcos.append(('iphone_configurado', 'Configuração inicial do iPhone feita'))
    if atual.status_aplicativo == 'C' and anterior.status_aplicativo != 'C':
        marcos.append(('instalacao_confirmada', 'Instalação do app confirmada'))
    if atual.icloud_confirmado_analista and not anterior.icloud_confirmado_analista:
        marcos.append(('icloud_validado', 'iCloud validado pela analista'))
    if _tem_imei(atual) and not _tem_imei(anterior):
        marcos.append(('aparelho_validado', 'Aparelho validado pela analista — venda liberada'))
    elif atual.status_aplicativo == 'I' and anterior.status_aplicativo != 'I':
        marcos.append(('instalacao_validada', 'Instalação validada pela analista'))
    if atual.venda_id and not anterior.venda_id:
        marcos.append(('venda_gerada', f'Venda #{atual.venda_id} gerada'))
    return marcos


def marcos_da_solicitacao(analise: AnaliseCreditoCliente, usuario=None) -> list[dict]:
    """Marcos do mais antigo para o mais recente (a SPA usa o último para "aguardando há X min")."""
    registros = list(
        analise.history.select_related('history_user').order_by('history_date', 'history_id')
    )
    usuario_id = getattr(usuario, 'id', None)
    marcos: list[Marco] = []
    for indice, registro in enumerate(registros):
        passagens = [('enviada', 'Solicitação enviada')] if indice == 0 else _transicoes(registros[indice - 1], registro)
        for tipo, titulo in passagens:
            marcos.append(Marco(
                tipo=tipo,
                titulo=titulo,
                data=registro.history_date,
                autor=_nome(registro.history_user),
                por_voce=bool(usuario_id) and registro.history_user_id == usuario_id,
            ))
    return [{**asdict(marco), 'data': marco.data.isoformat()} for marco in marcos]
