"""Endpoint de saúde usado pelo healthcheck do Docker, pelo autoheal e pelo deploy."""
from django.test import TestCase, override_settings


class HealthzTests(TestCase):
    def test_responde_200_sem_login(self):
        resposta = self.client.get("/healthz/")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"status": "ok"})

    @override_settings(ALLOWED_HOSTS=["credfacil.mobconnects.com"])
    def test_responde_para_host_interno_fora_do_allowed_hosts(self):
        # O healthcheck do container chama 127.0.0.1:8010; não pode virar 400
        # (senão o autoheal reiniciaria o container em loop).
        resposta = self.client.get("/healthz/", HTTP_HOST="127.0.0.1:8010")

        self.assertEqual(resposta.status_code, 200)

    def test_nao_cria_sessao_nem_toca_no_banco(self):
        with self.assertNumQueries(0):
            resposta = self.client.get("/healthz/")

        self.assertNotIn("sessionid", resposta.cookies)
