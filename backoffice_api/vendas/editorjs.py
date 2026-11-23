"""Contrato da loja (Editor.js) convertido em HTML seguro no servidor.

Faz o mesmo que `static/js/formatarTextoEditor.js` (header, paragraph e list;
outros blocos são ignorados), mas o texto inline passa por uma lista branca de
tags: nada de script, estilo, evento ou link que não seja http(s)/mailto.
"""
import json
from html import escape
from html.parser import HTMLParser

TAGS_PERMITIDAS = {'b', 'strong', 'i', 'em', 'u', 's', 'mark', 'code', 'sub', 'sup', 'span', 'a', 'br'}
TAGS_DESCARTADAS_COM_CONTEUDO = {'script', 'style', 'iframe', 'object', 'noscript', 'template'}
ESQUEMAS_DE_LINK = ('http://', 'https://', 'mailto:')
PROFUNDIDADE_MAXIMA_LISTA = 5


class _Sanitizador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.abertas: list[str] = []
        self.descartando = 0

    def handle_starttag(self, tag, attrs):
        if tag in TAGS_DESCARTADAS_COM_CONTEUDO:
            self.descartando += 1
            return
        if self.descartando or tag not in TAGS_PERMITIDAS:
            return
        if tag == 'br':
            self.partes.append('<br>')
            return
        atributos = ''
        if tag == 'a':
            href = (dict(attrs).get('href') or '').strip()
            if href.lower().startswith(ESQUEMAS_DE_LINK):
                atributos = f' href="{escape(href, quote=True)}"'
        self.partes.append(f'<{tag}{atributos}>')
        self.abertas.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == 'br' and not self.descartando:
            self.partes.append('<br>')

    def handle_endtag(self, tag):
        if tag in TAGS_DESCARTADAS_COM_CONTEUDO:
            self.descartando = max(0, self.descartando - 1)
            return
        if self.descartando or tag not in self.abertas:
            return
        while self.abertas:
            aberta = self.abertas.pop()
            self.partes.append(f'</{aberta}>')
            if aberta == tag:
                break

    def handle_data(self, data):
        if not self.descartando:
            self.partes.append(escape(data, quote=False))

    def resultado(self) -> str:
        fechamentos = [f'</{tag}>' for tag in reversed(self.abertas)]
        return ''.join(self.partes + fechamentos)


def sanitizar_inline(html: str) -> str:
    """Mantém só a formatação inline permitida; todo o resto vira texto escapado."""
    sanitizador = _Sanitizador()
    sanitizador.feed(str(html or ''))
    sanitizador.close()
    return sanitizador.resultado()


def _lista(dados: dict, profundidade: int = 0) -> str:
    tag = 'ol' if dados.get('style') == 'ordered' else 'ul'
    itens = []
    for item in dados.get('items') or []:
        if isinstance(item, dict):
            texto = sanitizar_inline(item.get('content', ''))
            filhos = item.get('items') or []
            if filhos and profundidade < PROFUNDIDADE_MAXIMA_LISTA:
                texto += _lista({'style': dados.get('style'), 'items': filhos}, profundidade + 1)
        else:
            texto = sanitizar_inline(item)
        itens.append(f'<li>{texto}</li>')
    return f'<{tag}>{"".join(itens)}</{tag}>'


def _bloco(bloco: dict) -> str:
    tipo = bloco.get('type')
    dados = bloco.get('data') if isinstance(bloco.get('data'), dict) else {}
    if tipo == 'paragraph':
        return f'<p>{sanitizar_inline(dados.get("text", ""))}</p>'
    if tipo == 'header':
        try:
            nivel = min(max(int(dados.get('level', 2)), 1), 6)
        except (TypeError, ValueError):
            nivel = 2
        return f'<h{nivel}>{sanitizar_inline(dados.get("text", ""))}</h{nivel}>'
    if tipo == 'list':
        return _lista(dados)
    return ''


def editorjs_para_html(conteudo) -> str:
    """HTML seguro a partir do JSON do Editor.js (dict ou texto). Conteúdo inválido → ''."""
    if isinstance(conteudo, str):
        try:
            conteudo = json.loads(conteudo)
        except ValueError:
            return ''
    blocos = conteudo.get('blocks') if isinstance(conteudo, dict) else None
    if not isinstance(blocos, list):
        return ''
    return ''.join(_bloco(bloco) for bloco in blocos if isinstance(bloco, dict))
