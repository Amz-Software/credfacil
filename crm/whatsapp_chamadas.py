"""Ligações pela Calling API da WhatsApp Cloud API (sinalização Graph + WebRTC).

Por padrão usa o mesmo número e token das mensagens. WHATSAPP_CHAMADAS_PHONE_NUMBER_ID e
WHATSAPP_CHAMADAS_TOKEN (opcionais) apontam as ligações para outro número, como o número de
teste da Meta, que não exige o limite de 2.000 contatos/dia do número de produção.
"""
import os
import uuid
from dataclasses import replace

from crm.whatsapp import Credenciais, ProviderMeta, credenciais

TEXTO_PEDIDO_PERMISSAO = 'Podemos te ligar pelo WhatsApp para falar sobre o seu atendimento?'


def credenciais_chamadas() -> Credenciais:
    base = credenciais()
    return replace(
        base,
        token=os.environ.get('WHATSAPP_CHAMADAS_TOKEN', '').strip() or base.token,
        phone_number_id=os.environ.get('WHATSAPP_CHAMADAS_PHONE_NUMBER_ID', '').strip() or base.phone_number_id,
    )


def numeros_aceitos() -> set[str]:
    """Números da empresa cujos eventos de ligação o webhook processa."""
    return {n for n in (credenciais().phone_number_id, credenciais_chamadas().phone_number_id) if n}


class ChamadasMeta:
    simulado = False

    def __init__(self, cred: Credenciais):
        self.cred = cred
        self.api = ProviderMeta(cred)

    @property
    def phone_number_id(self) -> str:
        return self.cred.phone_number_id

    def _calls(self, corpo: dict) -> dict:
        return self.api._post(f'{self.cred.phone_number_id}/calls', json={'messaging_product': 'whatsapp', **corpo})

    def aceitar(self, call_id: str, sdp: str) -> None:
        """pre_accept e accept com o mesmo SDP (a Meta exige igual); o áudio só sai depois do 200 do accept."""
        sessao = {'sdp_type': 'answer', 'sdp': sdp}
        self._calls({'call_id': call_id, 'action': 'pre_accept', 'session': sessao})
        self._calls({'call_id': call_id, 'action': 'accept', 'session': sessao})

    def recusar(self, call_id: str) -> None:
        self._calls({'call_id': call_id, 'action': 'reject'})

    def encerrar(self, call_id: str) -> None:
        self._calls({'call_id': call_id, 'action': 'terminate'})

    def ligar(self, para: str, sdp: str, referencia: str = '') -> str:
        corpo = {'to': para, 'action': 'connect', 'session': {'sdp_type': 'offer', 'sdp': sdp}}
        if referencia:
            corpo['biz_opaque_callback_data'] = referencia[:512]
        resposta = self._calls(corpo)
        return ((resposta.get('calls') or [{}])[0]).get('id', '')

    def permissao(self, para: str) -> str:
        """no_permission, temporary ou permanent."""
        resposta = self.api._get(f'{self.cred.phone_number_id}/call_permissions', params={'user_wa_id': para})
        return (resposta.get('permission') or {}).get('status', 'no_permission')

    def pedir_permissao(self, para: str, texto: str = TEXTO_PEDIDO_PERMISSAO) -> str:
        """Mensagem interativa da Meta pedindo permissão para ligar (só com a janela de 24 h aberta)."""
        return self.api._enviar(para, {'type': 'interactive', 'interactive': {
            'type': 'call_permission_request', 'action': {'name': 'call_permission_request'},
            'body': {'text': texto},
        }})

    def configuracao(self) -> dict:
        return self.api._get(f'{self.cred.phone_number_id}/settings').get('calling') or {}

    def configurar(self, calling: dict) -> dict:
        return self.api._post(f'{self.cred.phone_number_id}/settings', json={'calling': calling})


class ChamadasSimuladas:
    """Mesma interface sem rede (testes e ambiente sem credenciais)."""

    simulado = True
    permissao_padrao = 'temporary'

    def __init__(self, cred: Credenciais | None = None):
        self.cred = cred

    @property
    def phone_number_id(self) -> str:
        return (self.cred.phone_number_id if self.cred else '') or 'simulado'

    def aceitar(self, call_id, sdp):
        return None

    def recusar(self, call_id):
        return None

    def encerrar(self, call_id):
        return None

    def ligar(self, para, sdp, referencia=''):
        return f'wacid.sim.{uuid.uuid4().hex}'

    def permissao(self, para):
        return self.permissao_padrao

    def pedir_permissao(self, para, texto=TEXTO_PEDIDO_PERMISSAO):
        return f'sim.{uuid.uuid4().hex}'

    def configuracao(self):
        return {'status': 'NOT_SET'}

    def configurar(self, calling):
        return {'success': True}


def obter_chamadas():
    cred = credenciais_chamadas()
    return ChamadasMeta(cred) if cred.modo_real else ChamadasSimuladas(cred)
