"""Histórico da conversa no formato do Claude (só texto; blocos de ferramenta não são reenviados).

Entrada do cliente vira `user`, saída vira `assistant`. Mensagens seguidas do mesmo
lado são unidas. Saídas que não são do assistente levam um rótulo ([equipe] etc.).
"""
import re
from datetime import timedelta

from django.utils import timezone

from crm.models import Conversa, Mensagem
from crm.services.assistente import identidade

JANELA = timedelta(hours=72)
# CPF/data digitados há mais tempo que isso, sem identidade válida, são mascarados (não reidentificam).
JANELA_IDENTIFICACAO = timedelta(minutes=30)
MAX_MENSAGENS = 30
INICIO = '(início da conversa)'
SEM_TEXTO = '(o cliente não escreveu nada novo)'
# Resposta antiga com dados do cliente, de antes da identificação atual (ou sem identificação válida).
OCULTA = '[resposta com dados do cliente ocultada: para falar disso de novo, identifique o cliente outra vez]'
IGNORADAS = {Mensagem.Tipo.REACAO}
CPF = re.compile(r'\d{3}\s*\.?\s*\d{3}\s*\.?\s*\d{3}\s*-?\s*\d{2}')
DATA = re.compile(r'\b\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*\d{2,4}\b|\b\d{8}\b')


def _mascarar(texto: str) -> str:
    """Sem identidade válida, o CPF e a data que o cliente digitou antes não servem para reidentificar."""
    return DATA.sub('[data ocultada]', CPF.sub('[CPF ocultado]', texto))


def _deve_mascarar(mensagem: Mensagem, liberado_desde) -> bool:
    if liberado_desde is not None:
        return mensagem.criado_em < liberado_desde  # já identificado: os dados antigos não são mais necessários
    return timezone.now() - mensagem.criado_em > JANELA_IDENTIFICACAO


def _descrever_entrada(mensagem: Mensagem, liberado_desde) -> str:
    texto = mensagem.texto.strip()
    if _deve_mascarar(mensagem, liberado_desde):
        texto = _mascarar(texto)
    tipo = mensagem.tipo
    if tipo == Mensagem.Tipo.TEXTO:
        return texto
    if tipo == Mensagem.Tipo.AUDIO:
        ok = mensagem.transcricao_status == Mensagem.Transcricao.OK and texto
        return f'[áudio transcrito] {texto}' if ok else '[áudio que não foi possível transcrever]'
    nome = mensagem.get_tipo_display().lower()
    return f'[{nome} enviado: {texto}]' if texto else f'[{nome} enviado]'


def _descrever_saida(mensagem: Mensagem, liberado_desde) -> str:
    texto = mensagem.texto.strip() or f'[{mensagem.get_tipo_display().lower()}]'
    dados = mensagem.dados or {}
    if dados.get('pessoal') and (liberado_desde is None or mensagem.criado_em < liberado_desde):
        return OCULTA
    if dados.get('ia'):
        return texto
    if mensagem.autor == Mensagem.Autor.HUMANO:
        return f'[equipe] {texto}'
    if mensagem.origem == Mensagem.Origem.ABERTURA:
        return f'[mensagem enviada pela empresa] {texto}'
    return f'[mensagem automática] {texto}'


def _papel(mensagem: Mensagem) -> str:
    return 'user' if mensagem.direcao == Mensagem.Direcao.ENTRADA else 'assistant'


def _mensagens_recentes(conversa: Conversa) -> list[Mensagem]:
    desde = timezone.now() - JANELA
    recentes = (Mensagem.objects
                .filter(conversa=conversa, criado_em__gte=desde)
                .exclude(tipo__in=IGNORADAS)
                .exclude(direcao=Mensagem.Direcao.SAIDA, status=Mensagem.Status.ERRO)
                .order_by('-criado_em', '-id')[:MAX_MENSAGENS])
    return list(reversed(recentes))


def montar(conversa: Conversa) -> list[dict]:
    liberado_desde = identidade.verificado_em(conversa)
    blocos: list[dict] = []
    for mensagem in _mensagens_recentes(conversa):
        papel = _papel(mensagem)
        texto = (_descrever_entrada(mensagem, liberado_desde) if papel == 'user'
                 else _descrever_saida(mensagem, liberado_desde))
        if not texto:
            continue
        if blocos and blocos[-1]['role'] == papel:
            blocos[-1] = {'role': papel, 'content': f"{blocos[-1]['content']}\n\n{texto}"}
        else:
            blocos.append({'role': papel, 'content': texto})
    if not blocos or blocos[0]['role'] != 'user':
        blocos.insert(0, {'role': 'user', 'content': INICIO})
    if blocos[-1]['role'] != 'user':
        blocos.append({'role': 'user', 'content': SEM_TEXTO})
    return blocos
