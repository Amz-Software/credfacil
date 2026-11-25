"""Versão no ar (commit do deploy). A página guarda a versão com que foi aberta e o
navegador (static/js/versao.js) pergunta a atual: se mudou, oferece "Atualizar".

O deploy faz `git merge` na pasta montada em /app e reinicia o web; como o valor
fica em cache por processo, cada processo novo já responde com o commit novo.
APP_VERSAO no ambiente tem prioridade (útil fora de um checkout do git).
"""
import os
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, JsonResponse

TAMANHO_VERSAO = 12
SEM_VERSAO = 'dev'


def _ler_git(base: Path) -> str:
    """Commit do HEAD lendo os arquivos do .git (sem chamar o git: o container roda sem permissão)."""
    pasta = base / '.git'
    cabeca = (pasta / 'HEAD').read_text().strip()
    if not cabeca.startswith('ref:'):
        return cabeca  # HEAD destacado: já é o commit
    referencia = cabeca.split(' ', 1)[1].strip()
    arquivo = pasta / referencia
    if arquivo.exists():
        return arquivo.read_text().strip()
    empacotadas = pasta / 'packed-refs'
    for linha in empacotadas.read_text().splitlines() if empacotadas.exists() else []:
        if linha.endswith(f' {referencia}'):
            return linha.split(' ', 1)[0]
    return ''


@lru_cache(maxsize=1)
def versao_atual() -> str:
    valor = os.environ.get('APP_VERSAO', '').strip()
    if not valor:
        try:
            valor = _ler_git(Path(settings.BASE_DIR))
        except OSError:
            valor = ''
    return (valor or SEM_VERSAO)[:TAMANHO_VERSAO]


def contexto(request: HttpRequest) -> dict:
    return {'versao_app': versao_atual()}


def versao(request: HttpRequest) -> JsonResponse:
    """Só para quem está logado; sem cache, senão o navegador nunca vê a versão nova."""
    if not request.user.is_authenticated:
        resposta = JsonResponse({'detail': 'Faça login.'}, status=401)
    else:
        resposta = JsonResponse({'versao': versao_atual()})
    resposta['Cache-Control'] = 'no-store'
    return resposta
