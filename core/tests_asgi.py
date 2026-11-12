"""Reproduz a causa raiz do incidente de 2026-11-12.

Um request síncrono preso, ao ser cancelado (cliente desconectou / timeout do
proxy), fazia o asgiref chamar `executor.shutdown(wait=True)` DENTRO do event
loop. O loop inteiro ficava esperando a thread presa e o servidor parava de
atender todo mundo. Com o patch, o cancelamento libera o loop na hora.
"""
import asyncio
import importlib
import threading
import time
from contextlib import suppress

from asgiref.sync import ThreadSensitiveContext, sync_to_async
from django.test import SimpleTestCase

from core import asgiref_patch

ESPERA_DA_THREAD_PRESA_S = 3
ORIGINAL_AEXIT = ThreadSensitiveContext.__aexit__  # capturado antes de qualquer patch


def _cancelar_request_preso() -> float:
    """Cancela um 'request' preso numa thread síncrona; retorna quanto o loop ficou bloqueado."""
    liberar = threading.Event()

    async def request_preso():
        async with ThreadSensitiveContext():
            await sync_to_async(liberar.wait, thread_sensitive=True)(ESPERA_DA_THREAD_PRESA_S)

    async def cenario() -> float:
        tarefa = asyncio.create_task(request_preso())
        await asyncio.sleep(0.2)  # a thread já está presa
        inicio = time.monotonic()
        tarefa.cancel()
        with suppress(asyncio.CancelledError):
            await tarefa
        return time.monotonic() - inicio

    try:
        return asyncio.run(cenario())
    finally:
        liberar.set()


class CancelamentoDeRequestPresoTests(SimpleTestCase):
    def test_cancelar_request_preso_nao_bloqueia_o_event_loop(self):
        asgiref_patch.aplicar()

        bloqueio = _cancelar_request_preso()

        self.assertLess(bloqueio, 1, f"event loop ficou bloqueado {bloqueio:.1f}s esperando a thread presa")

    def test_patch_e_aplicado_pela_aplicacao_asgi(self):
        import core.asgi

        aexit_patcheado = ThreadSensitiveContext.__aexit__
        ThreadSensitiveContext.__aexit__ = ORIGINAL_AEXIT
        delattr(ThreadSensitiveContext, asgiref_patch._MARCADOR)
        try:
            importlib.reload(core.asgi)  # carregar a aplicação ASGI deve aplicar o patch

            self.assertTrue(asgiref_patch.esta_aplicado())
        finally:
            ThreadSensitiveContext.__aexit__ = aexit_patcheado
            setattr(ThreadSensitiveContext, asgiref_patch._MARCADOR, True)

    def test_aplicar_duas_vezes_e_seguro(self):
        asgiref_patch.aplicar()
        asgiref_patch.aplicar()

        self.assertTrue(asgiref_patch.esta_aplicado())
