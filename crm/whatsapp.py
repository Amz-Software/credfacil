"""Cliente da WhatsApp Cloud API (Graph) e provider simulado.

O modo real só liga com WHATSAPP_TOKEN e WHATSAPP_PHONE_NUMBER_ID. Sem eles, o
provider simulado grava ids falsos e nada sai para a Meta (princípio 9 da arquitetura).
"""
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field

import requests

from crm.erros_meta import traduzir_erro

logger = logging.getLogger(__name__)

GRAPH_URL = 'https://graph.facebook.com'
VERSAO_PADRAO = 'v23.0'
TIMEOUT_SEGUNDOS = 20
TIMEOUT_DOWNLOAD_SEGUNDOS = 60
BLOCO_DOWNLOAD = 1024 * 1024
IDIOMA_TEMPLATE = 'pt_BR'


class ErroWhatsApp(Exception):
    def __init__(self, mensagem: str, codigo: int | None = None):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


@dataclass(frozen=True)
class Credenciais:
    # Segredos fora do repr: não aparecem em log nem na página de erro do Django.
    token: str = field(repr=False)
    phone_number_id: str
    waba_id: str
    app_secret: str = field(repr=False)
    verify_token: str = field(repr=False)
    versao: str

    @property
    def modo_real(self) -> bool:
        return bool(self.token and self.phone_number_id)


def credenciais() -> Credenciais:
    """Lidas do ambiente a cada chamada: trocar o .env e reiniciar já vale."""
    return Credenciais(
        token=os.environ.get('WHATSAPP_TOKEN', '').strip(),
        phone_number_id=os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '').strip(),
        waba_id=os.environ.get('WHATSAPP_WABA_ID', '').strip(),
        app_secret=os.environ.get('WHATSAPP_APP_SECRET', '').strip(),
        verify_token=os.environ.get('WHATSAPP_VERIFY_TOKEN', '').strip(),
        versao=os.environ.get('WHATSAPP_API_VERSION', VERSAO_PADRAO).strip() or VERSAO_PADRAO,
    )


class ProviderMeta:
    simulado = False

    def __init__(self, cred: Credenciais):
        self.cred = cred
        self.base = f'{GRAPH_URL}/{cred.versao}'

    # --- infraestrutura -------------------------------------------------
    def __repr__(self) -> str:
        return f'ProviderMeta(versao={self.cred.versao!r})'

    def _headers(self) -> dict:
        return {'Authorization': f'Bearer {self.cred.token}'}

    def _tratar(self, resposta: requests.Response) -> dict:
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {}
        if resposta.ok and 'error' not in corpo:
            return corpo
        erro = corpo.get('error', {}) if isinstance(corpo, dict) else {}
        codigo = erro.get('code')
        detalhe = (erro.get('error_data') or {}).get('details') or erro.get('error_user_msg') or ''
        mensagem = traduzir_erro(codigo, erro.get('message', ''), detalhe or erro.get('message', ''))
        logger.warning('Erro da Meta %s: %s', codigo, erro.get('message'))
        raise ErroWhatsApp(mensagem, codigo)

    def _post(self, caminho: str, **kwargs) -> dict:
        try:
            resposta = requests.post(f'{self.base}/{caminho}', headers=self._headers(),
                                     timeout=TIMEOUT_SEGUNDOS, **kwargs)
        except requests.RequestException as exc:
            raise ErroWhatsApp(f'Sem comunicação com a Meta: {exc.__class__.__name__}.') from exc
        return self._tratar(resposta)

    def _get(self, caminho: str, params: dict | None = None) -> dict:
        try:
            resposta = requests.get(f'{self.base}/{caminho}', headers=self._headers(),
                                    params=params, timeout=TIMEOUT_SEGUNDOS)
        except requests.RequestException as exc:
            raise ErroWhatsApp(f'Sem comunicação com a Meta: {exc.__class__.__name__}.') from exc
        return self._tratar(resposta)

    def _enviar(self, para: str, corpo: dict, responde_a: str = '') -> str:
        payload = {'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': para, **corpo}
        if responde_a:
            payload['context'] = {'message_id': responde_a}
        resposta = self._post(f'{self.cred.phone_number_id}/messages', json=payload)
        mensagens = resposta.get('messages') or [{}]
        return mensagens[0].get('id', '')

    # --- envio ------------------------------------------------------------
    def enviar_texto(self, para: str, texto: str, responde_a: str = '') -> str:
        return self._enviar(para, {'type': 'text', 'text': {'body': texto, 'preview_url': True}}, responde_a)

    def enviar_template(self, para: str, nome: str, parametros: list[str]) -> str:
        componentes = []
        if parametros:
            componentes.append({
                'type': 'body',
                'parameters': [{'type': 'text', 'text': valor} for valor in parametros],
            })
        corpo = {'type': 'template', 'template': {
            'name': nome, 'language': {'code': IDIOMA_TEMPLATE}, 'components': componentes,
        }}
        return self._enviar(para, corpo)

    def subir_midia(self, conteudo: bytes, mime: str, nome: str) -> str:
        resposta = self._post(
            f'{self.cred.phone_number_id}/media',
            data={'messaging_product': 'whatsapp', 'type': mime},
            files={'file': (nome, conteudo, mime)},
        )
        return resposta.get('id', '')

    def enviar_midia(self, para: str, tipo_meta: str, media_id: str, legenda: str = '',
                     nome_arquivo: str = '', voz: bool = False, responde_a: str = '') -> str:
        objeto: dict = {'id': media_id}
        if legenda and tipo_meta in ('image', 'video', 'document'):
            objeto['caption'] = legenda
        if tipo_meta == 'document' and nome_arquivo:
            objeto['filename'] = nome_arquivo
        if tipo_meta == 'audio' and voz:
            objeto['voice'] = True
        return self._enviar(para, {'type': tipo_meta, tipo_meta: objeto}, responde_a)

    def reagir(self, para: str, wa_message_id: str, emoji: str) -> str:
        return self._enviar(para, {'type': 'reaction', 'reaction': {'message_id': wa_message_id, 'emoji': emoji}})

    def marcar_lida(self, wa_message_id: str, digitando: bool = False) -> None:
        payload = {'messaging_product': 'whatsapp', 'status': 'read', 'message_id': wa_message_id}
        if digitando:
            payload['typing_indicator'] = {'type': 'text'}
        self._post(f'{self.cred.phone_number_id}/messages', json=payload)

    # --- mídia recebida ---------------------------------------------------
    def baixar_midia(self, media_id: str, limite_bytes: int) -> tuple[str, str, str]:
        """Grava em arquivo temporário, em blocos (nada inteiro na memória).

        Devolve (caminho do temporário, mime, sha256 anunciado). Quem chama apaga o arquivo.
        """
        info = self._get(media_id)
        url = info.get('url')
        if not url:
            raise ErroWhatsApp('A Meta não informou o endereço da mídia.')
        temporario = tempfile.NamedTemporaryFile(delete=False, prefix='crm-midia-')
        try:
            with requests.get(url, headers=self._headers(), stream=True, timeout=TIMEOUT_DOWNLOAD_SEGUNDOS) as resp:
                if not resp.ok:
                    raise ErroWhatsApp(f'Falha ao baixar a mídia (HTTP {resp.status_code}).')
                total = 0
                for bloco in resp.iter_content(BLOCO_DOWNLOAD):
                    total += len(bloco)
                    if total > limite_bytes:
                        raise ErroWhatsApp('Arquivo acima do limite permitido.')
                    temporario.write(bloco)
        except requests.RequestException as exc:
            temporario.close()
            os.unlink(temporario.name)
            raise ErroWhatsApp(f'Falha ao baixar a mídia: {exc.__class__.__name__}.') from exc
        except Exception:
            temporario.close()
            os.unlink(temporario.name)
            raise
        temporario.close()
        return temporario.name, info.get('mime_type', ''), info.get('sha256', '')

    # --- templates ----------------------------------------------------------
    def criar_template(self, nome: str, corpo_meta: str, exemplos: list[str]) -> dict:
        if not self.cred.waba_id:
            raise ErroWhatsApp('Falta WHATSAPP_WABA_ID para criar mensagens de abertura.')
        componente = {'type': 'BODY', 'text': corpo_meta}
        if exemplos:
            componente['example'] = {'body_text': [exemplos]}
        resposta = self._post(f'{self.cred.waba_id}/message_templates', json={
            'name': nome, 'language': IDIOMA_TEMPLATE, 'category': 'UTILITY',
            'parameter_format': 'positional', 'components': [componente],
        })
        return {'id': str(resposta.get('id', '')), 'status': resposta.get('status', 'PENDING'),
                'categoria': resposta.get('category', '')}

    def consultar_template(self, nome: str) -> dict | None:
        if not self.cred.waba_id:
            return None
        resposta = self._get(f'{self.cred.waba_id}/message_templates', params={
            'name': nome, 'fields': 'id,name,status,category,rejected_reason', 'limit': 10,
        })
        for item in resposta.get('data', []):
            if item.get('name') == nome:
                return {'id': str(item.get('id', '')), 'status': item.get('status', ''),
                        'categoria': item.get('category', ''), 'motivo': item.get('rejected_reason', '') or ''}
        return None


class ProviderSimulado:
    """Mesma interface, sem rede. Templates ficam 'em análise' até o simulador decidir."""

    simulado = True

    def __init__(self, cred: Credenciais | None = None):
        self.cred = cred

    @staticmethod
    def _wamid() -> str:
        return f'sim.{uuid.uuid4().hex}'

    def enviar_texto(self, para, texto, responde_a=''):
        return self._wamid()

    def enviar_template(self, para, nome, parametros):
        return self._wamid()

    def subir_midia(self, conteudo, mime, nome):
        return f'sim-media.{uuid.uuid4().hex}'

    def enviar_midia(self, para, tipo_meta, media_id, legenda='', nome_arquivo='', voz=False, responde_a=''):
        return self._wamid()

    def reagir(self, para, wa_message_id, emoji):
        return self._wamid()

    def marcar_lida(self, wa_message_id, digitando=False):
        return None

    def baixar_midia(self, media_id, limite_bytes):
        raise ErroWhatsApp('Mídia indisponível no modo simulado.')

    def criar_template(self, nome, corpo_meta, exemplos):
        return {'id': f'sim-tpl.{uuid.uuid4().hex[:12]}', 'status': 'PENDING', 'categoria': 'UTILITY'}

    def consultar_template(self, nome):
        return None


def obter_provider():
    cred = credenciais()
    return ProviderMeta(cred) if cred.modo_real else ProviderSimulado(cred)


def modo_integracao() -> str:
    return 'real' if credenciais().modo_real else 'simulado'
