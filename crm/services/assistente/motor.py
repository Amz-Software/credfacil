"""Um turno do assistente: histórico → Claude ↔ ferramentas → resposta no WhatsApp.

Qualquer falha antes de responder vira FalhaAssistente; quem chama decide o plano B
(menu de autoatendimento ou fila da equipe). Nada é enviado pela metade.
"""
import json
import logging
import re
import time
from datetime import timedelta

from django.utils import timezone

from crm.models import LIMITE_TEXTO, ConfiguracaoCRM, Conversa, Mensagem
from crm.services.assistente import historico, ia, identidade, instrucoes
from crm.services.assistente.ferramentas import DEFINICOES, ErroFerramenta, Turno, executar

logger = logging.getLogger(__name__)

MAX_VOLTAS = 8
MAX_SEGUNDOS_POR_TURNO = 90
MAX_RESPOSTAS_POR_HORA = 40
# Qualquer coisa que o WhatsApp transforma em link: com esquema, www. ou domínio.tld (ex.: wa.me/..., bit.ly/...).
LINK = re.compile(
    r'(?:https?://|www\.)[^\s)>\]]+'
    r'|\b(?:[a-z0-9-]+\.)+(?:com|net|org|br|io|app|link|site|xyz|info)\b(?:/[^\s)>\]]*)?'
    r'|\b(?:[a-z0-9-]+\.)+(?:me|ly|co|gl|to)/[^\s)>\]]*',  # TLDs curtos e ambíguos só com caminho (wa.me/…)
    re.IGNORECASE,
)
JA_FALHOU = ('Esta chamada já falhou com os mesmos parâmetros. Corrija conforme o erro anterior ou use '
             'transferir_para_atendente.')
ERRO_INTERNO = 'Erro interno ao executar a ferramenta.'
AVISO_TRANSFERENCIA = 'Certo! Já chamei alguém da nossa equipe. Em instantes vamos te responder por aqui.'
NOTA_NAO_ENTREGUE = ('O assistente de IA respondeu, mas o WhatsApp não entregou a mensagem. '
                     'Confira a conversa e responda pela equipe.')


class FalhaAssistente(Exception):
    """O assistente não conseguiu responder; nada foi enviado ao cliente."""


def _excedeu_limite(conversa: Conversa) -> bool:
    desde = timezone.now() - timedelta(hours=1)
    return (Mensagem.objects.filter(conversa=conversa, direcao=Mensagem.Direcao.SAIDA, criado_em__gte=desde,
                                    dados__ia=True).count() >= MAX_RESPOSTAS_POR_HORA)


def _resultado(turno: Turno, chamada: ia.Chamada, falhas: set[str]) -> dict:
    assinatura = f'{chamada.nome}:{json.dumps(chamada.entrada, sort_keys=True, ensure_ascii=False)}'
    if assinatura in falhas:
        return {'type': 'tool_result', 'tool_use_id': chamada.id, 'content': JA_FALHOU, 'is_error': True}
    try:
        dados = executar(turno, chamada.nome, chamada.entrada)
    except ErroFerramenta as erro:
        falhas.add(assinatura)
        return {'type': 'tool_result', 'tool_use_id': chamada.id, 'content': str(erro), 'is_error': True}
    except Exception:  # noqa: BLE001 — o modelo recebe um erro genérico e decide (transferir)
        logger.exception('Falha na ferramenta %s da conversa %s.', chamada.nome, turno.conversa.pk)
        falhas.add(assinatura)
        return {'type': 'tool_result', 'tool_use_id': chamada.id, 'content': ERRO_INTERNO, 'is_error': True}
    return {'type': 'tool_result', 'tool_use_id': chamada.id, 'content': json.dumps(dados, ensure_ascii=False)}


def _manter_trava(conversa: Conversa) -> None:
    """Turnos com ferramentas demoram: renova a trava para outra thread não pegar a conversa."""
    Conversa.objects.filter(pk=conversa.pk).update(processando_desde=timezone.now())


def _conversar(turno: Turno) -> str:
    system = instrucoes.montar_system(turno.conversa)
    mensagens = historico.montar(turno.conversa)
    falhas: set[str] = set()
    inicio = time.monotonic()
    for _ in range(MAX_VOLTAS):
        if time.monotonic() - inicio > MAX_SEGUNDOS_POR_TURNO:
            break
        _manter_trava(turno.conversa)
        resposta = ia.chamar(system, DEFINICOES, mensagens)
        if resposta.stop_reason == 'tool_use' and resposta.chamadas:
            resultados = [_resultado(turno, chamada, falhas) for chamada in resposta.chamadas]
            mensagens = [*mensagens, {'role': 'assistant', 'content': resposta.conteudo},
                         {'role': 'user', 'content': resultados}]
            continue
        if resposta.stop_reason == 'pause_turn':
            mensagens = [*mensagens, {'role': 'assistant', 'content': resposta.conteudo}]
            continue
        return resposta.texto
    raise ia.FalhaIA('Turno sem resposta final (limite de voltas ou de tempo).')


def _host(endereco: str) -> str:
    sem_esquema = re.sub(r'^https?://', '', endereco.strip().lower())
    return sem_esquema.split('/', 1)[0].split(':', 1)[0].rstrip('.,;!?')


def _links_permitidos(texto: str) -> bool:
    """Só sai link do próprio sistema (com ou sem http://, que o WhatsApp também deixa clicável)."""
    base = _host(ConfiguracaoCRM.obter().url_publica)
    return all(base and _host(link) == base for link in LINK.findall(texto))


def _enviar(conversa: Conversa, texto: str, pessoal: bool) -> None:
    from crm.services import envio
    from crm.services.conversas import transferir

    mensagem = envio.enviar_texto(conversa, texto[:LIMITE_TEXTO], usuario=None, autor=Mensagem.Autor.AUTOMATICO,
                                  exigir_trava=False)
    dados = {**(mensagem.dados or {}), 'ia': True, **({'pessoal': True} if pessoal else {})}
    Mensagem.objects.filter(pk=mensagem.pk).update(dados=dados)
    if mensagem.status == Mensagem.Status.ERRO:
        transferir(conversa, NOTA_NAO_ENTREGUE)


def _texto_do_turno(turno: Turno) -> str:
    try:
        texto = _conversar(turno)
    except ia.FalhaIA as erro:
        if not turno.transferiu:
            raise FalhaAssistente(str(erro)) from erro
        return AVISO_TRANSFERENCIA  # a transferência já aconteceu: só falta avisar o cliente
    except Exception as erro:  # noqa: BLE001 — erro inesperado (SDK, banco): plano B em vez de fila silenciosa
        logger.exception('Erro inesperado no assistente da conversa %s.', turno.conversa.pk)
        if turno.transferiu:
            return AVISO_TRANSFERENCIA
        raise FalhaAssistente('Erro inesperado no assistente.') from erro
    texto = texto.strip()
    if texto:
        return texto
    if turno.transferiu:
        return AVISO_TRANSFERENCIA
    raise FalhaAssistente('O modelo terminou sem texto para o cliente.')


def atender(conversa: Conversa) -> None:
    if _excedeu_limite(conversa):
        raise FalhaAssistente(f'Mais de {MAX_RESPOSTAS_POR_HORA} respostas da IA na última hora.')
    turno = Turno(conversa=conversa)
    texto = _texto_do_turno(turno)
    if not _links_permitidos(texto):
        logger.warning('Assistente tentou enviar link de fora do sistema na conversa %s.', conversa.pk)
        if turno.transferiu:
            texto = AVISO_TRANSFERENCIA
        else:
            raise FalhaAssistente('Resposta com link de fora do sistema.')
    conversa.refresh_from_db(fields=['modo'])
    if conversa.modo != Conversa.Modo.AUTOMATICO and not turno.transferiu:
        logger.info('Conversa %s foi assumida pela equipe durante o turno da IA; resposta descartada.', conversa.pk)
        return
    # Com cliente identificado, qualquer resposta pode repetir dados dele (mesmo sem ferramenta neste turno).
    pessoal = turno.usou_dados or bool(identidade.clientes_verificados(conversa))
    _enviar(conversa, texto, pessoal=pessoal)
