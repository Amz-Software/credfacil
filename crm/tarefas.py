"""Execução em segundo plano depois do commit (envio de mídia, processamento, eventos).

Threads de um executor por processo, como no restante do sistema. As rotinas do
`crm_rotinas` recuperam o que uma thread interrompida (deploy, reinício) deixou pela metade.
Nos testes, `CRM_TAREFAS_SINCRONAS = True` roda tudo na hora.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, transaction

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='crm')


def _executar(funcao, args, kwargs) -> None:
    close_old_connections()
    try:
        funcao(*args, **kwargs)
    except Exception:  # noqa: BLE001 — tarefa de fundo nunca derruba o processo
        logger.exception('Falha na tarefa de fundo do CRM: %s', getattr(funcao, '__name__', funcao))
    finally:
        close_old_connections()


def agendar(funcao, *args, **kwargs) -> None:
    """Roda `funcao` depois do commit da transação atual."""
    def disparar():
        if getattr(settings, 'CRM_TAREFAS_SINCRONAS', False):
            funcao(*args, **kwargs)
            return
        try:
            _executor.submit(_executar, funcao, args, kwargs)
        except RuntimeError:
            logger.warning('Tarefa do CRM descartada: processo encerrando.')

    transaction.on_commit(disparar)
