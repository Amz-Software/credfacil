"""Worker uvicorn usado pelo gunicorn em produção (ver gunicorn.conf.py)."""
from uvicorn_worker import UvicornWorker


class CredfacilUvicornWorker(UvicornWorker):
    # Django/Channels não implementam o protocolo "lifespan"; desligar evita
    # erro/ruído no boot de cada worker.
    CONFIG_KWARGS = {**UvicornWorker.CONFIG_KWARGS, "lifespan": "off"}
