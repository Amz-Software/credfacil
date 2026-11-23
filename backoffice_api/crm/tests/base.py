"""Base dos testes da API do CRM: WhatsApp simulado (sem credenciais), tarefas síncronas e sessão do backoffice.

Reaproveita `crm.tests.base.CrmTestCase` (isolamento da Meta, mídia em pasta temporária, WebSocket
desligado, `receber()`) e troca os usuários por usuários com acesso ao backoffice.
"""
import io

from django.contrib.auth.models import Permission

from backoffice_api.models import RegistroAuditoria
from backoffice_api.tests.fabricas import cliente_logado, criar_usuario
from crm.tests.base import CrmTestCase
from vendas.models import Cliente, ComprovantesCliente

API = '/api/bo/v1/crm/'
ACESSAR = 'crm.acessar_crm'
GERENCIAR = 'crm.gerenciar_crm'


def url(caminho: str) -> str:
    return f'{API}{caminho}'


def png() -> bytes:
    from PIL import Image

    saida = io.BytesIO()
    Image.new('RGB', (40, 30), 'red').save(saida, format='PNG')
    return saida.getvalue()


class CrmApiTestCase(CrmTestCase):
    def setUp(self):
        super().setUp()
        self.atendente = criar_usuario('atendente1', permissoes=(ACESSAR,))
        self.outro = criar_usuario('atendente2', permissoes=(ACESSAR,))
        self.gestor = criar_usuario('gestora', permissoes=(ACESSAR, GERENCIAR))
        self.sem_acesso = criar_usuario('semcrm')
        self._clientes = {}

    def api(self, usuario=None):
        """APIClient logado pelo endpoint de login do backoffice (sessão + CSRF)."""
        usuario = usuario or self.atendente
        if usuario.pk not in self._clientes:
            self._clientes[usuario.pk] = cliente_logado(usuario)
        return self._clientes[usuario.pk]

    def dar_permissao(self, usuario, *codigos: str):
        for codigo in codigos:
            app_label, codename = codigo.split('.', 1)
            usuario.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
        self._clientes.pop(usuario.pk, None)
        return type(usuario).objects.get(pk=usuario.pk)  # descarta o cache de permissões

    def auditorias(self, acao: str):
        return RegistroAuditoria.objects.filter(acao=acao)

    def criar_cliente(self, loja, nome: str = 'Maria Souza', telefone: str = '(91) 99999-0000') -> Cliente:
        return Cliente.objects.create(
            nome=nome, telefone=telefone, cpf='12345678900', nascimento='1990-01-01', rg='1',
            cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
            comprovantes=ComprovantesCliente.objects.create(loja=loja),
        )

    def erro(self, resposta) -> dict:
        return resposta.json()['erro']
