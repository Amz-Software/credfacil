"""Regras de acesso e de apresentação do módulo de crédito.

As regras de grupo que hoje só existem nas views Django antigas foram trazidas
para cá (sem alterar as views), para a API não depender delas:

- `pode_observar`: `vendas/views/analise.py:_pode_observar_solicitacao`;
- `pode_gerenciar_serasa_pre_analise`: `vendas/views/pre_analise.py:_pode_gerenciar_consulta_serasa`;
- `etapa_da_analise`: coluna "Status Geral" de `cliente/cliente_list.html`.
"""
import re

from accounts.permissions import user_is_analista_or_admin
from vendas.models import AnaliseCreditoCliente

PERMISSAO_VER = 'vendas.view_cliente'
PERMISSAO_VER_TODAS = 'vendas.view_all_analise_credito'
PERMISSAO_VER_SERASA = 'vendas.view_consulta_serasa'
PERMISSAO_DECIDIR = 'vendas.change_status_analise'
PERMISSAO_EDITAR_VENDA_FINALIZADA = 'vendas.can_edit_finished_sale'

GRUPO_ANALISTA = 'ANALISTA'
GRUPO_ADMINISTRADOR = 'ADMINISTRADOR'
GRUPOS_OBSERVACAO = ('ANALISTA', 'ADMINISTRADOR', 'SUPERADMIN')
# Criar solicitação pelo backoffice (sempre na loja da CredFácil/IPIXX).
GRUPOS_CRIACAO = ('ANALISTA', 'ADMINISTRADOR', 'SUPERADMIN')
GRUPOS_NUMERO_AUTENTICADOR = ('ANALISTA', 'ADMINISTRADOR')

STATUS_EM_ANALISE = 'EA'
STATUS_APROVADO = 'A'
STATUS_REPROVADO = 'R'
STATUS_CANCELADO = 'C'
APP_CONFIRMACAO_PENDENTE = 'C'
APP_INSTALADO = 'I'

ROTULOS_STATUS = dict(AnaliseCreditoCliente.STATUS_CHOICES)
ROTULOS_STATUS_APP = dict(AnaliseCreditoCliente.STATUS_APP_CHOICES)

DIGITOS_CPF = 11


def _grupos(user) -> frozenset[str]:
    """Nomes dos grupos do usuário, consultados uma vez por requisição."""
    cache = getattr(user, '_bo_credito_grupos', None)
    if cache is None:
        cache = frozenset(user.groups.values_list('name', flat=True))
        user._bo_credito_grupos = cache
    return cache


def eh_analista(user) -> bool:
    """Grupo ANALISTA (sem atalho de superusuário: é a regra de `vendas/services/analise.py`)."""
    return GRUPO_ANALISTA in _grupos(user)


def _em_algum_grupo(user, grupos) -> bool:
    return bool(user.is_superuser or _grupos(user) & set(grupos))


def pode_ver_serasa(user) -> bool:
    """Consulta Serasa e restrição: grupo ANALISTA ou `view_consulta_serasa`."""
    return bool(user.is_superuser or eh_analista(user) or user.has_perm(PERMISSAO_VER_SERASA))


def pode_gerenciar_serasa_pre_analise(user) -> bool:
    """Anexar, remover e abrir a consulta Serasa da pré-análise (regra da tela atual)."""
    return bool(
        user.is_superuser
        or user.has_perm(PERMISSAO_DECIDIR)
        or user.has_perm(PERMISSAO_VER_SERASA)
        or eh_analista(user)
    )


def pode_observar(user) -> bool:
    return _em_algum_grupo(user, GRUPOS_OBSERVACAO)


def pode_ver_numero_autenticador(user) -> bool:
    return _em_algum_grupo(user, GRUPOS_NUMERO_AUTENTICADOR)


def pode_editar_apos_venda(user) -> bool:
    """Depois da venda gerada só ANALISTA/ADMINISTRADOR ou `can_edit_finished_sale` editam."""
    return bool(user_is_analista_or_admin(user) or user.has_perm(PERMISSAO_EDITAR_VENDA_FINALIZADA))


def permissao_ver_serasa(request, view) -> bool:
    """Exigência no formato do núcleo (`permissoes = {...: [permissao_ver_serasa]}`)."""
    return pode_ver_serasa(request.user)


def permissao_gerenciar_serasa_pre_analise(request, view) -> bool:
    return pode_gerenciar_serasa_pre_analise(request.user)


def mascarar_cpf(cpf: str | None) -> str:
    """`12345678901` -> `***.456.789-**`; o que não tiver 11 dígitos vira `***`."""
    digitos = re.sub(r'\D', '', cpf or '')
    if len(digitos) != DIGITOS_CPF:
        return '***'
    return f'***.{digitos[3:6]}.{digitos[6:9]}-**'


def nome_usuario(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.username


def referencia_usuario(user) -> dict | None:
    if user is None:
        return None
    return {'id': user.pk, 'nome': nome_usuario(user)}


ETAPAS = {
    'finalizado': 'Finalizado',
    'pronto_para_venda': 'Pronto para venda',
    'aguardando_imei': 'Aguardando IMEI',
    'aguardando_configuracao_inicial': 'Aguardando configuração inicial',
    'aguardando_confirmacao': 'Aguardando confirmação',
    'aguardando_qr_code': 'Aguardando QR code',
    'pendente': 'Pendente',
}


def etapa_da_analise(analise: AnaliseCreditoCliente) -> str:
    """Etapa operacional da solicitação (mesma leitura da coluna "Status Geral" da tela)."""
    if analise.venda_id:
        return 'finalizado'
    tem_imei = bool(analise.imei_id)
    if analise.produto.is_iphone:
        if tem_imei:
            return 'pronto_para_venda'
        if analise.icloud_configurado_vendedor:
            return 'aguardando_imei'
        return 'aguardando_configuracao_inicial'
    status_app = analise.status_aplicativo
    if status_app == APP_INSTALADO and tem_imei:
        return 'pronto_para_venda'
    if status_app == APP_CONFIRMACAO_PENDENTE:
        return 'aguardando_confirmacao' if tem_imei else 'aguardando_imei'
    if status_app == 'P':
        return 'aguardando_qr_code'
    return 'pendente'
