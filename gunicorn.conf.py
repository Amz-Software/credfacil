"""Configuração do servidor de produção (HTTP + WebSocket via ASGI).

Por que gunicorn + uvicorn em vez de daphne (incidente de 2026-11-12):
- daphne roda 1 processo sem vigia; um event loop travado derruba tudo até
  alguém reiniciar o container na mão;
- aqui o gunicorn mantém N workers e mata/recria qualquer worker cujo event
  loop pare de dar sinal de vida por `timeout` segundos. Requests longos não
  disparam isso: views síncronas rodam em threads, fora do event loop.

Os WebSockets continuam funcionando com vários workers porque os grupos de
notificação passam pelo Redis (channel layer).
"""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8010')}"
worker_class = "core.uvicorn_worker.CredfacilUvicornWorker"

# 2 workers cabem na VPS (≈ 600 MB cada); ajustável sem rebuild via env.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))

# Watchdog: worker sem sinal de vida por 30s é morto e recriado.
timeout = 30
graceful_timeout = 30

# Heartbeat em memória, não no disco do container (a VPS já ficou sem disco).
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

# Recicla cada worker algumas vezes por dia: segura o crescimento de memória
# (o daphne foi de 256 MB a 650 MB em 26h). Valor alto porque reciclar derruba
# os WebSockets daquele worker (os fronts reconectam sozinhos).
max_requests = 50000
max_requests_jitter = 5000

accesslog = "-"
errorlog = "-"
loglevel = "info"
