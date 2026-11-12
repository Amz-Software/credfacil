"""Correção do deadlock do asgiref que derrubou a produção em 2026-11-12.

`asgiref.sync.ThreadSensitiveContext.__aexit__` chama `executor.shutdown()`
(wait=True) DENTRO do event loop. Se o request é cancelado (cliente
desconectou, timeout do proxy) enquanto a thread síncrona dele está presa, o
loop inteiro fica esperando essa thread e o servidor para de atender todos.

O patch troca por `shutdown(wait=False)`: o executor daquele request é
descartado sem esperar; a thread presa termina sozinha quando puder (o
resultado é ignorado) e o loop segue atendendo os demais.

Revisar ao atualizar o asgiref (fixado em requirements.txt): se o upstream
corrigir, este módulo pode ser removido. Coberto por core/tests_asgi.py.
"""
import logging

from asgiref.sync import SyncToAsync, ThreadSensitiveContext

logger = logging.getLogger(__name__)

_MARCADOR = "_credfacil_shutdown_sem_espera"


async def _aexit_sem_esperar(self, exc, value, tb):
    if not self.token:
        return

    executor = SyncToAsync.context_to_thread_executor.pop(self, None)
    if executor:
        executor.shutdown(wait=False)
    SyncToAsync.thread_sensitive_context.reset(self.token)


def esta_aplicado() -> bool:
    return getattr(ThreadSensitiveContext, _MARCADOR, False)


def aplicar() -> None:
    if esta_aplicado():
        return
    if not hasattr(SyncToAsync, "context_to_thread_executor") or not hasattr(
        SyncToAsync, "thread_sensitive_context"
    ):
        logger.error("asgiref mudou internamente; patch do ThreadSensitiveContext NÃO aplicado.")
        return

    ThreadSensitiveContext.__aexit__ = _aexit_sem_esperar
    setattr(ThreadSensitiveContext, _MARCADOR, True)
