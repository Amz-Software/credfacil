"""Histórico da conversa no formato do Claude (blocos de ferramenta não são reenviados).

Entrada do cliente vira `user`, saída vira `assistant`. Mensagens seguidas do mesmo
lado são unidas. Saídas que não são do assistente levam um rótulo ([equipe] etc.).
As imagens/PDFs mais recentes do cliente vão como arquivo (o assistente vê o comprovante).
"""
import re
from datetime import timedelta

from django.utils import timezone

from crm.models import Conversa, Mensagem, TentativaContato
from crm.services.assistente import anexos, identidade

JANELA = timedelta(hours=72)
# CPF/data digitados há mais tempo que isso, sem identidade válida, são mascarados (não reidentificam).
JANELA_IDENTIFICACAO = timedelta(minutes=30)
MAX_MENSAGENS = 30
INICIO = '(início da conversa)'
SEM_TEXTO = '(o cliente não escreveu nada novo)'
# Resposta antiga com dados do cliente, de antes da identificação atual (ou sem identificação válida).
OCULTA = '[resposta com dados do cliente ocultada: para falar disso de novo, identifique o cliente outra vez]'
AVISO_OCULTO = ('[aviso automático de cobrança enviado pela empresa: {etapa}. Os valores ficam ocultos até o '
                'cliente se identificar]')
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
    oculta = dados.get('pessoal') and (liberado_desde is None or mensagem.criado_em < liberado_desde)
    cobranca = dados.get('cobranca')
    if cobranca:
        tipo = cobranca.get('tipo')
        etapa = TentativaContato.Tipo(tipo).label.lower() if tipo in TentativaContato.Tipo.values else 'cobrança'
        return AVISO_OCULTO.format(etapa=etapa) if oculta else f'[aviso automático de cobrança] {texto}'
    if oculta:
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


def _juntar(partes: list[dict], novas: list[dict]) -> list[dict]:
    """Texto seguido de texto vira um bloco só (separado por linha em branco)."""
    resultado = list(partes)
    for parte in novas:
        if resultado and resultado[-1]['type'] == 'text' and parte['type'] == 'text':
            resultado[-1] = {'type': 'text', 'text': f"{resultado[-1]['text']}\n\n{parte['text']}"}
        else:
            resultado.append(parte)
    return resultado


def _conteudo(partes: list[dict]):
    """Só texto → string (formato mais simples); com arquivo → lista de blocos."""
    if all(p['type'] == 'text' for p in partes):
        return '\n\n'.join(p['text'] for p in partes)
    return partes


def montar(conversa: Conversa) -> list[dict]:
    liberado_desde = identidade.verificado_em(conversa)
    visiveis = anexos.ids_visiveis(conversa)
    turnos: list[tuple[str, list[dict]]] = []
    for mensagem in _mensagens_recentes(conversa):
        papel = _papel(mensagem)
        texto = (_descrever_entrada(mensagem, liberado_desde) if papel == 'user'
                 else _descrever_saida(mensagem, liberado_desde))
        partes = [{'type': 'text', 'text': texto}] if texto else []
        if papel == 'user' and mensagem.pk in visiveis:
            partes += anexos.blocos_de_visao(mensagem)
        if not partes:
            continue
        if turnos and turnos[-1][0] == papel:
            turnos[-1] = (papel, _juntar(turnos[-1][1], partes))
        else:
            turnos.append((papel, partes))
    blocos = [{'role': papel, 'content': _conteudo(partes)} for papel, partes in turnos]
    if not blocos or blocos[0]['role'] != 'user':
        blocos.insert(0, {'role': 'user', 'content': INICIO})
    if blocos[-1]['role'] != 'user':
        blocos.append({'role': 'user', 'content': SEM_TEXTO})
    return blocos
