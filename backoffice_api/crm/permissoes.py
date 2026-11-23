"""Exigências de permissão do CRM na API do backoffice (mesmas regras de `crm/permissoes.py`).

`ACESSO` em tudo; `GERENCIA` na configuração. Não há escopo por loja no CRM: quem tem
`crm.acessar_crm` vê todas as conversas (o painel do cliente aplica o escopo de lojas
do resto do sistema em `crm.services.organizacao.painel`).
"""
from backoffice_api.nucleo.permissoes import PermissaoNegada
from crm.permissoes import pode_acessar, pode_gerenciar

MENSAGEM_SEM_ACESSO = 'Você não tem acesso ao CRM de WhatsApp.'
MENSAGEM_SEM_GERENCIA = 'Só quem gerencia o CRM pode fazer isso.'


class AcessoCrm:
    """`crm.acessar_crm` (direta, por grupo ou superusuário)."""

    def avaliar(self, user) -> bool:
        if not pode_acessar(user):
            raise PermissaoNegada(MENSAGEM_SEM_ACESSO)
        return True


class GerenciaCrm:
    """`crm.gerenciar_crm`, que só vale junto com `crm.acessar_crm`."""

    def avaliar(self, user) -> bool:
        if not pode_gerenciar(user):
            raise PermissaoNegada(MENSAGEM_SEM_GERENCIA)
        return True


ACESSO = [AcessoCrm()]
GERENCIA = [AcessoCrm(), GerenciaCrm()]
