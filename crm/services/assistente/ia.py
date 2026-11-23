"""Chamada ao Claude (SDK oficial). Sem ANTHROPIC_API_KEY o assistente fica indisponível.

Variáveis de ambiente (segredos só no .env do servidor):
- ANTHROPIC_API_KEY: obrigatória para ligar o assistente.
- ASSISTENTE_MODELO: padrão claude-sonnet-5-5 (escolha do produto).
- ASSISTENTE_ESFORCO: padrão low (conversa de WhatsApp não ganha com raciocínio longo).
- ASSISTENTE_TELEFONES_TESTE: opcional; se preenchida, só esses números falam com a IA (teste em produção).
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MODELO_PADRAO = 'claude-sonnet-5-5'
ESFORCO_PADRAO = 'low'
ESFORCOS_VALIDOS = {'low', 'medium', 'high', 'xhigh', 'max'}
MAX_TOKENS = 4096
# Curto de propósito: as threads do worker são compartilhadas com o resto do CRM.
TIMEOUT_SEGUNDOS = 25.0
TENTATIVAS = 1
# Numa recusa por política, a API refaz a chamada em outro modelo (Sonnet 5.5 aceita a forma "default").
BETA_FALLBACK = 'server-side-fallback-2026-07-01'
MODELOS_COM_FALLBACK = {'claude-sonnet-5-5', 'claude-opus-5-5', 'claude-opus-5', 'claude-fable-5-2', 'claude-fable-5-1'}


class FalhaIA(Exception):
    """A API não respondeu de forma utilizável (rede, limite, recusa, erro do servidor)."""


@dataclass(frozen=True)
class Chamada:
    id: str
    nome: str
    entrada: dict


@dataclass(frozen=True)
class RespostaIA:
    stop_reason: str
    textos: tuple[str, ...]
    chamadas: tuple[Chamada, ...]
    conteudo: list[Any] = field(default_factory=list)  # blocos brutos, devolvidos sem alteração

    @property
    def texto(self) -> str:
        return '\n\n'.join(t.strip() for t in self.textos if t.strip())


def chave() -> str:
    return os.environ.get('ANTHROPIC_API_KEY', '').strip()


def disponivel() -> bool:
    return bool(chave())


def liberado_para(telefone: str) -> bool:
    """Com ASSISTENTE_TELEFONES_TESTE preenchida (números separados por vírgula), só eles falam com a IA."""
    lista = os.environ.get('ASSISTENTE_TELEFONES_TESTE', '').strip()
    if not lista:
        return True
    # Preenchida mas inválida libera ninguém (falha fechada, nunca todos).
    permitidos = {''.join(c for c in item if c.isdigit()) for item in lista.split(',')} - {''}
    return ''.join(c for c in telefone if c.isdigit()) in permitidos


def modelo() -> str:
    return os.environ.get('ASSISTENTE_MODELO', '').strip() or MODELO_PADRAO


def esforco() -> str:
    valor = os.environ.get('ASSISTENTE_ESFORCO', '').strip().lower()
    return valor if valor in ESFORCOS_VALIDOS else ESFORCO_PADRAO


def _cliente():
    import anthropic  # import tardio: o resto do CRM funciona sem o pacote configurado

    return anthropic.Anthropic(api_key=chave(), timeout=TIMEOUT_SEGUNDOS, max_retries=TENTATIVAS)


def _normalizar(resposta) -> RespostaIA:
    textos, chamadas = [], []
    for bloco in resposta.content:
        if bloco.type == 'fallback':
            textos, chamadas = [], []  # o que veio antes é do modelo que recusou: não vai ao cliente
        elif bloco.type == 'text':
            textos.append(bloco.text)
        elif bloco.type == 'tool_use':
            entrada = bloco.input if isinstance(bloco.input, dict) else {}
            chamadas.append(Chamada(id=bloco.id, nome=bloco.name, entrada=entrada))
    return RespostaIA(stop_reason=resposta.stop_reason or '', textos=tuple(textos),
                      chamadas=tuple(chamadas), conteudo=list(resposta.content))


def chamar(system: list[dict], ferramentas: list[dict], mensagens: list[dict]) -> RespostaIA:
    """Uma volta do modelo. Erros da API viram FalhaIA (o motor decide o plano B)."""
    import anthropic

    nome_modelo = modelo()
    parametros: dict[str, Any] = {
        'model': nome_modelo,
        'max_tokens': MAX_TOKENS,
        'system': system,
        'tools': ferramentas,
        'messages': mensagens,
        'output_config': {'effort': esforco()},
        'cache_control': {'type': 'ephemeral'},  # cache automático no fim do histórico
    }
    try:
        if nome_modelo in MODELOS_COM_FALLBACK:
            resposta = _cliente().beta.messages.create(betas=[BETA_FALLBACK], fallbacks='default', **parametros)
        else:
            resposta = _cliente().messages.create(**parametros)
    except anthropic.APIStatusError as erro:
        logger.warning('Claude respondeu %s (request-id %s).', erro.status_code,
                       erro.response.headers.get('request-id', '-'))
        raise FalhaIA(f'Erro {erro.status_code} na API do Claude.') from erro
    except anthropic.APIConnectionError as erro:
        logger.warning('Sem conexão com a API do Claude: %s', erro)
        raise FalhaIA('Sem conexão com a API do Claude.') from erro
    _registrar_uso(resposta)
    if resposta.stop_reason == 'refusal':
        raise FalhaIA('O modelo recusou a resposta.')
    if resposta.stop_reason == 'max_tokens':
        raise FalhaIA('Resposta cortada pelo limite de tamanho.')
    return _normalizar(resposta)


def _registrar_uso(resposta) -> None:
    uso = getattr(resposta, 'usage', None)
    if uso is None:
        return
    logger.info(
        'Assistente IA: modelo=%s entrada=%s cache_gravado=%s cache_lido=%s saida=%s stop=%s',
        getattr(resposta, 'model', '-'), uso.input_tokens, getattr(uso, 'cache_creation_input_tokens', 0),
        getattr(uso, 'cache_read_input_tokens', 0), uso.output_tokens, resposta.stop_reason,
    )
