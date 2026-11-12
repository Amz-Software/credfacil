"""Testes do envio de notificações em tempo real (WebSocket).

Contexto (incidente de 2026-11-12): um `group_send` no Redis travou dentro do
request de criação de pré-análise rápida. Ao cancelar o request, o daphne
bloqueou o event loop inteiro (asgiref espera a thread presa) e o sistema caiu.
Regra: o envio WS NUNCA pode rodar dentro do request nem esperar sem limite.
"""
import asyncio
import threading
import time
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from notificacao import utils


def _instancia_falsa():
    return SimpleNamespace(
        criado_em=timezone.now(),
        get_absolute_url=lambda: "/pre-analises-rapidas/1/",
    )


def _enviar(usuario_id=7, **extra):
    utils.enviar_ws_para_usuario(
        usuario=SimpleNamespace(id=usuario_id),
        instance=_instancia_falsa(),
        notification_id=99,
        verb="Nova análise",
        description="CPF 000",
        target_url=None,
        type_notification="pre_analise_rapida",
        event="pre_analise_criada",
        **extra,
    )


class CamadaFalsa:
    """Channel layer falso: registra chamadas e pode travar ou falhar."""

    def __init__(self, atraso=0.0, erro=None):
        self.atraso = atraso
        self.erro = erro
        self.chamadas = []
        self.concluido = threading.Event()

    async def group_send(self, grupo, mensagem):
        self.chamadas.append((grupo, mensagem))
        try:
            if self.atraso:
                await asyncio.sleep(self.atraso)
            if self.erro:
                raise self.erro
        finally:
            self.concluido.set()


class EnvioWsTests(TestCase):
    def _com_camada(self, camada):
        return mock.patch.object(utils, "get_channel_layer", return_value=camada)

    @override_settings(NOTIFICACAO_WS_SINCRONO=True)
    def test_so_envia_depois_do_commit(self):
        camada = CamadaFalsa()
        with self._com_camada(camada):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                _enviar()
            self.assertEqual(camada.chamadas, [], "não pode enviar antes do commit")

            for callback in callbacks:
                callback()

        self.assertEqual(len(camada.chamadas), 1)
        grupo, mensagem = camada.chamadas[0]
        self.assertEqual(grupo, "user_7")
        self.assertEqual(mensagem["type"], "send_notification")
        self.assertEqual(mensagem["notification_id"], 99)
        self.assertEqual(mensagem["event"], "pre_analise_criada")
        self.assertEqual(mensagem["target_url"], "/pre-analises-rapidas/1/")

    @override_settings(NOTIFICACAO_WS_SINCRONO=False, NOTIFICACAO_WS_TIMEOUT=5)
    def test_redis_travado_nao_prende_o_request(self):
        camada = CamadaFalsa(atraso=2)
        with self._com_camada(camada):
            inicio = time.monotonic()
            with self.captureOnCommitCallbacks(execute=True):
                _enviar()
            duracao = time.monotonic() - inicio
            camada.concluido.wait(timeout=5)

        self.assertLess(duracao, 0.5, "o envio WS deve rodar fora da thread do request")
        self.assertEqual(len(camada.chamadas), 1, "o envio deve acontecer em segundo plano")

    @override_settings(NOTIFICACAO_WS_SINCRONO=True, NOTIFICACAO_WS_TIMEOUT=0.2)
    def test_envio_que_trava_e_abortado_pelo_timeout(self):
        camada = CamadaFalsa(atraso=10)
        with self._com_camada(camada), self.assertLogs(utils.logger, "WARNING") as logs:
            inicio = time.monotonic()
            with self.captureOnCommitCallbacks(execute=True):
                _enviar()
            duracao = time.monotonic() - inicio

        self.assertLess(duracao, 2, "group_send sem resposta deve ser abortado pelo timeout")
        self.assertIn("user_7", "\n".join(logs.output))

    @override_settings(NOTIFICACAO_WS_SINCRONO=False, NOTIFICACAO_WS_TIMEOUT=5)
    def test_eventos_chegam_na_ordem_em_que_foram_gerados(self):
        # Ex.: 'proposta_criada' seguido de 'proposta_aceita' — o front abre
        # modais pelo campo `event`, então a ordem importa.
        entregues = []
        todos_entregues = threading.Event()

        class CamadaOrdenada:
            async def group_send(self, grupo, mensagem):
                if mensagem["verb"] == "primeiro":
                    await asyncio.sleep(0.3)  # o primeiro envio é o mais lento
                entregues.append(mensagem["verb"])
                if len(entregues) == 2:
                    todos_entregues.set()

        with self._com_camada(CamadaOrdenada()):
            with self.captureOnCommitCallbacks(execute=True):
                for verbo in ("primeiro", "segundo"):
                    utils.enviar_ws_para_usuario(
                        SimpleNamespace(id=7), _instancia_falsa(), 1, verbo, "d", None,
                    )
            todos_entregues.wait(timeout=5)

        self.assertEqual(entregues, ["primeiro", "segundo"])

    @override_settings(NOTIFICACAO_WS_SINCRONO=False)
    def test_falha_ao_agendar_no_desligamento_nao_quebra_o_request(self):
        executor_desligado = mock.Mock(submit=mock.Mock(side_effect=RuntimeError("shutdown")))
        with mock.patch.object(utils, "_executor", executor_desligado), \
                self.assertLogs(utils.logger, "WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                _enviar()  # não pode levantar exceção

    @override_settings(NOTIFICACAO_WS_SINCRONO=True)
    def test_falha_do_redis_e_registrada_e_nao_propaga(self):
        camada = CamadaFalsa(erro=ConnectionError("redis fora"))
        with self._com_camada(camada), self.assertLogs(utils.logger, "WARNING"):
            with self.captureOnCommitCallbacks(execute=True):
                _enviar()  # não pode levantar exceção

        self.assertEqual(len(camada.chamadas), 1)
