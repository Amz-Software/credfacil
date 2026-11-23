"""Quem o cliente provou ser nesta conversa (CPF + data de nascimento conferidos pelo código).

A IA nunca decide identidade: ela só repassa o que o cliente digitou para
`identificar`, e as ferramentas de consulta leem daqui quais clientes estão liberados.
Estado em Conversa.contexto['ia'] = {clientes: [ids], verificado_em: ISO, falhas: n, ultima_falha: ISO}.
Além do limite por conversa há um limite por CPF (cache, CPF em hash), contra quem
tenta datas de nascimento de um mesmo CPF a partir de vários números.
"""
import hashlib
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from crm.models import Conversa
from crm.services.autoatendimento import cpf_valido, ler_data
from crm.telefone import somente_digitos

logger = logging.getLogger(__name__)

CHAVE = 'ia'
VALIDADE = timedelta(hours=24)
EXPIRACAO_FALHAS = timedelta(hours=24)
MAX_FALHAS = 3
MAX_FALHAS_POR_CPF = 5
MAX_CLIENTES_VINCULADOS = 5
LIMITE_ATINGIDO = ('Limite de tentativas de identificação atingido. Não tente de novo: transfira para um '
                   'atendente com transferir_para_atendente.')


class ErroIdentificacao(Exception):
    """Mensagem pronta para o modelo explicar ao cliente (ou transferir)."""


def _ler_momento(valor) -> datetime | None:
    try:
        momento = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None
    return momento if timezone.is_aware(momento) else None


def _estado(conversa: Conversa) -> dict:
    return dict((conversa.contexto or {}).get(CHAVE) or {})


def _gravar(conversa: Conversa, estado: dict) -> None:
    # Só a chave da IA: limpa o que o menu de autoatendimento tinha deixado (etapa, cpf digitado).
    contexto = {CHAVE: estado}
    Conversa.objects.filter(pk=conversa.pk).update(contexto=contexto)
    conversa.contexto = contexto


def verificado_em(conversa: Conversa) -> datetime | None:
    """Momento da identificação ainda válida, ou None."""
    estado = _estado(conversa)
    momento = _ler_momento(estado.get('verificado_em'))
    if momento is None or not estado.get('clientes'):
        return None
    return momento if timezone.now() - momento <= VALIDADE else None


def clientes_verificados(conversa: Conversa) -> list[int]:
    return list(_estado(conversa)['clientes']) if verificado_em(conversa) else []


def falhas(conversa: Conversa) -> int:
    estado = _estado(conversa)
    ultima = _ler_momento(estado.get('ultima_falha'))
    if ultima is None or timezone.now() - ultima > EXPIRACAO_FALHAS:
        return 0
    return int(estado.get('falhas', 0))


def _chave_cpf(cpf: str) -> str:
    return 'crm:ia:falhas_cpf:' + hashlib.sha256(cpf.encode()).hexdigest()


def _cache():
    """Cache compartilhado entre processos (Redis em produção); o local só se o Redis falhar."""
    return caches[getattr(settings, 'CRM_CACHE_LIMITES', 'default')]


def _contar_falha_do_cpf(cpf: str) -> None:
    chave, prazo = _chave_cpf(cpf), int(EXPIRACAO_FALHAS.total_seconds())
    try:
        # add só grava se não existe: o prazo conta da primeira falha e não se renova a cada tentativa.
        if not _cache().add(chave, 1, prazo):
            _cache().incr(chave)
    except Exception:  # noqa: BLE001 — sem Redis, o limite por conversa continua valendo
        logger.warning('Cache de limites indisponível; falha por CPF não contabilizada.', exc_info=True)


def _registrar_falha(conversa: Conversa, cpf: str = '') -> int:
    total = falhas(conversa) + 1
    _gravar(conversa, {**_estado(conversa), 'falhas': total, 'ultima_falha': timezone.now().isoformat()})
    if cpf:
        _contar_falha_do_cpf(cpf)
    return total


def _cpf_bloqueado(cpf: str) -> bool:
    try:
        return int(_cache().get(_chave_cpf(cpf), 0)) >= MAX_FALHAS_POR_CPF
    except Exception:  # noqa: BLE001
        logger.warning('Cache de limites indisponível; checagem por CPF ignorada.', exc_info=True)
        return False


def identificar(conversa: Conversa, cpf: str, nascimento: str) -> list:
    """Confere CPF + nascimento. Devolve os clientes encontrados ou levanta ErroIdentificacao."""
    from vendas.models import Cliente

    digitos = somente_digitos(str(cpf or ''))
    if falhas(conversa) >= MAX_FALHAS or (digitos and _cpf_bloqueado(digitos)):
        raise ErroIdentificacao(LIMITE_ATINGIDO)
    if not cpf_valido(digitos):
        _registrar_falha(conversa)
        raise ErroIdentificacao('CPF inválido (precisa ter 11 dígitos válidos). Peça para o cliente conferir.')
    data = ler_data(str(nascimento or ''))
    if data is None:
        _registrar_falha(conversa)
        raise ErroIdentificacao('Data de nascimento ilegível. Peça no formato dia/mês/ano, ex.: 17/05/1990.')
    clientes = list(Cliente.objects.filter(cpf=digitos, nascimento=data)[:MAX_CLIENTES_VINCULADOS])
    if not clientes:
        total = _registrar_falha(conversa, digitos)
        restantes = max(MAX_FALHAS - total, 0)
        raise ErroIdentificacao(
            'Nenhum cadastro com esse CPF e data de nascimento. Não diga qual dos dois está errado. '
            + (f'O cliente pode tentar mais {restantes} vez(es).' if restantes else
               'Acabaram as tentativas: transfira para um atendente.')
        )
    conversa.clientes.add(*clientes)
    _gravar(conversa, {'clientes': [c.pk for c in clientes], 'verificado_em': timezone.now().isoformat(),
                       'falhas': 0})
    return clientes
