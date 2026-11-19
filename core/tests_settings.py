"""Configuração lida do ambiente: cada caso importa as settings num processo novo."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE_DIR = Path(__file__).resolve().parent.parent

SCRIPT = """
import json
from django.conf import settings
print(json.dumps({
    "engine": settings.DATABASES["default"]["ENGINE"],
    "channel_host": settings.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]["address"],
    "select2": settings.CACHES["select2"]["LOCATION"],
    "default_cache": settings.CACHES["default"]["BACKEND"],
    "sentry_dsn": settings.SENTRY_DSN,
    "sentry_pii": settings.SENTRY_SEND_DEFAULT_PII,
}))
"""


def carregar_settings(**env):
    ambiente = {**os.environ, "DJANGO_SETTINGS_MODULE": "core.settings", **env}
    resultado = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=BASE_DIR, env=ambiente, capture_output=True, text=True, timeout=60,
    )
    if resultado.returncode != 0:
        raise AssertionError(resultado.stderr)
    return json.loads(resultado.stdout.strip().splitlines()[-1])


class SettingsAmbienteTests(SimpleTestCase):
    def test_db_used_vazio_usa_sqlite(self):
        config = carregar_settings(DB_USED="", SENTRY_DSN="")
        self.assertEqual(config["engine"], "django.db.backends.sqlite3")

    def test_db_used_invalido_falha_com_mensagem_clara(self):
        ambiente = {**os.environ, "DJANGO_SETTINGS_MODULE": "core.settings",
                    "DB_USED": "postgres", "SENTRY_DSN": ""}
        resultado = subprocess.run(
            [sys.executable, "-c", SCRIPT], cwd=BASE_DIR, env=ambiente,
            capture_output=True, text=True, timeout=60,
        )
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("DB_USED inválido", resultado.stderr)

    def test_channel_layer_e_cache_usam_o_mesmo_redis(self):
        config = carregar_settings(
            REDIS_HOST="meu-redis", REDIS_PORT="6390", REDIS_DB="3", SENTRY_DSN="",
        )
        self.assertEqual(config["channel_host"], "redis://meu-redis:6390")
        self.assertEqual(config["select2"], "redis://meu-redis:6390/3")
        self.assertEqual(config["default_cache"], "django.core.cache.backends.locmem.LocMemCache")

    def test_redis_padrao_quando_variaveis_ausentes(self):
        config = carregar_settings(REDIS_HOST="", REDIS_PORT="", REDIS_DB="", SENTRY_DSN="")
        self.assertEqual(config["channel_host"], "redis://redis:6379")
        self.assertEqual(config["select2"], "redis://redis:6379/0")

    def test_sentry_dsn_vem_do_ambiente_e_pii_desligado_por_padrao(self):
        config = carregar_settings(SENTRY_DSN="")
        self.assertEqual(config["sentry_dsn"], "")
        self.assertFalse(config["sentry_pii"])

    def test_sentry_pii_pode_ser_ligado(self):
        config = carregar_settings(SENTRY_DSN="", SENTRY_SEND_DEFAULT_PII="True")
        self.assertTrue(config["sentry_pii"])
