"""Webhook da WhatsApp Cloud API (arquitetura §6.1).

GET: handshake do cadastro no painel da Meta. POST: assinatura HMAC-SHA256 obrigatória;
responde 200 sempre (exceções só no log) para a Meta não reentregar em loop.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone as dt_timezone

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.debug import sensitive_variables
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from crm.models import Mensagem
from crm.services.conversas import EntradaNormalizada, receber_mensagem
from crm.services.envio import aplicar_status
from crm.whatsapp import credenciais

logger = logging.getLogger(__name__)

TIPOS_MIDIA = {
    'audio': Mensagem.Tipo.AUDIO,
    'image': Mensagem.Tipo.IMAGEM,
    'video': Mensagem.Tipo.VIDEO,
    'document': Mensagem.Tipo.DOCUMENTO,
    'sticker': Mensagem.Tipo.FIGURINHA,
}
CODIGO_ARQUIVO_GRANDE = 131052


@sensitive_variables('segredo', 'esperado')
def assinatura_valida(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    """HMAC-SHA256 do corpo bruto. Compara bytes: texto não ASCII nunca vira exceção."""
    if not segredo or not cabecalho or not cabecalho.startswith('sha256='):
        return False
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest().encode()
    recebido = cabecalho.removeprefix('sha256=').encode('utf-8', 'replace')
    return hmac.compare_digest(recebido, esperado)


@sensitive_variables('esperado', 'recebido')
def token_verificacao_valido(recebido: str, esperado: str) -> bool:
    if not esperado:
        return False
    return hmac.compare_digest((recebido or '').encode('utf-8', 'replace'), esperado.encode())


def _quando(timestamp) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


def normalizar(mensagem: dict, nomes: dict[str, str]) -> EntradaNormalizada:
    """Converte um item de `messages[]` da Meta para o formato interno."""
    tipo_meta = mensagem.get('type', '')
    telefone = mensagem.get('from', '')
    dados: dict = {}
    texto, midia_id, midia_meta, tipo = '', '', None, Mensagem.Tipo.DESCONHECIDO
    contexto = mensagem.get('context') or {}
    if contexto.get('forwarded') or contexto.get('frequently_forwarded'):
        dados['encaminhada'] = True

    if tipo_meta == 'text':
        tipo, texto = Mensagem.Tipo.TEXTO, (mensagem.get('text') or {}).get('body', '')
    elif tipo_meta == 'button':
        tipo, texto = Mensagem.Tipo.TEXTO, (mensagem.get('button') or {}).get('text', '')
        dados['botao_payload'] = (mensagem.get('button') or {}).get('payload', '')
    elif tipo_meta == 'interactive':
        interativo = mensagem.get('interactive') or {}
        resposta = interativo.get('button_reply') or interativo.get('list_reply') or {}
        tipo, texto = Mensagem.Tipo.TEXTO, resposta.get('title', '')
    elif tipo_meta in TIPOS_MIDIA:
        objeto = mensagem.get(tipo_meta) or {}
        tipo, midia_id = TIPOS_MIDIA[tipo_meta], objeto.get('id', '')
        texto = objeto.get('caption', '')
        midia_meta = {'mime': objeto.get('mime_type', ''), 'sha256': objeto.get('sha256', ''),
                      'nome_original': objeto.get('filename', ''), 'voz': bool(objeto.get('voice'))}
    elif tipo_meta == 'location':
        local = mensagem.get('location') or {}
        tipo = Mensagem.Tipo.LOCALIZACAO
        dados['localizacao'] = {chave: local.get(chave) for chave in ('latitude', 'longitude', 'name', 'address', 'url')
                                if local.get(chave) is not None}
    elif tipo_meta == 'contacts':
        tipo = Mensagem.Tipo.CONTATO
        dados['contatos'] = [{
            'nome': (c.get('name') or {}).get('formatted_name', ''),
            'telefones': [{'numero': t.get('phone', ''), 'wa_id': t.get('wa_id', '')} for t in c.get('phones', [])],
        } for c in mensagem.get('contacts', [])]
    elif tipo_meta == 'reaction':
        reacao = mensagem.get('reaction') or {}
        tipo = Mensagem.Tipo.REACAO
        dados['reacao'] = {'emoji': reacao.get('emoji', ''), 'alvo_wa_id': reacao.get('message_id', '')}
    else:
        erro = (mensagem.get('errors') or [{}])[0]
        dados['tipo_meta'] = tipo_meta
        if erro:
            dados['erro'] = {'codigo': erro.get('code'), 'titulo': erro.get('title', ''),
                             'detalhe': (erro.get('error_data') or {}).get('details', '')}
            if erro.get('code') == CODIGO_ARQUIVO_GRANDE:
                texto = '[arquivo grande demais]'

    return EntradaNormalizada(
        telefone=telefone, wa_message_id=mensagem.get('id', ''), tipo=tipo, texto=texto,
        contato_nome=nomes.get(telefone, ''), context_wa_id=contexto.get('id', ''),
        midia_id=midia_id, midia_meta=midia_meta, dados=dados, criado_em=_quando(mensagem.get('timestamp')),
    )


def processar_payload(payload: dict) -> None:
    for entrada in payload.get('entry', []):
        for mudanca in entrada.get('changes', []):
            if mudanca.get('field') != 'messages':
                continue
            valor = mudanca.get('value') or {}
            nomes = {c.get('wa_id', ''): (c.get('profile') or {}).get('name', '') for c in valor.get('contacts', [])}
            for mensagem in valor.get('messages', []):
                try:
                    receber_mensagem(normalizar(mensagem, nomes))
                except Exception:  # noqa: BLE001
                    logger.exception('Falha ao gravar mensagem do webhook %s.', mensagem.get('id'))
            for status in valor.get('statuses', []):
                try:
                    aplicar_status(status.get('id', ''), status.get('status', ''), status.get('errors'))
                except Exception:  # noqa: BLE001
                    logger.exception('Falha ao aplicar status %s.', status.get('id'))


@method_decorator(csrf_exempt, name='dispatch')
class WebhookWhatsAppView(View):
    def get(self, request):
        modo_ok = request.GET.get('hub.mode') == 'subscribe'
        if modo_ok and token_verificacao_valido(request.GET.get('hub.verify_token', ''), credenciais().verify_token):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponseForbidden('Token de verificação inválido.')

    def post(self, request):
        corpo = request.body
        try:
            valida = assinatura_valida(corpo, request.headers.get('X-Hub-Signature-256', ''), credenciais().app_secret)
        except Exception:  # noqa: BLE001 — qualquer falha na conferência é recusa, nunca 500
            valida = False
        if not valida:
            logger.warning('Webhook do WhatsApp recusado: assinatura inválida ou WHATSAPP_APP_SECRET ausente.')
            return HttpResponseForbidden('Assinatura inválida.')
        try:
            processar_payload(json.loads(corpo or b'{}'))
        except Exception:  # noqa: BLE001 — sempre 200 para a Meta não reentregar em loop
            logger.exception('Falha ao processar o webhook do WhatsApp.')
        return JsonResponse({'status': 'ok'})
