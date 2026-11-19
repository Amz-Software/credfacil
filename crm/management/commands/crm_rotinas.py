import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from crm.services.rotinas import rodar_tudo

logger = logging.getLogger(__name__)

INTERVALO_SEGUNDOS = 60
CICLOS_POR_SINCRONIA_DE_ABERTURAS = 10


class Command(BaseCommand):
    help = 'Rotinas do CRM de WhatsApp (programadas, lembretes, mídias, aberturas). Use --loop no worker.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true', help='Roda para sempre, a cada minuto.')

    def handle(self, *args, **opcoes):
        settings.CRM_TAREFAS_SINCRONAS = True  # no worker não há request esperando: roda na hora
        if not opcoes['loop']:
            self.stdout.write(str(rodar_tudo()))
            return
        parar = {'sinal': False}
        signal.signal(signal.SIGTERM, lambda *_: parar.update(sinal=True))
        ciclo = 0
        self.stdout.write('crm_rotinas: iniciado.')
        while not parar['sinal']:
            close_old_connections()
            resultado = rodar_tudo(incluir_aberturas=ciclo % CICLOS_POR_SINCRONIA_DE_ABERTURAS == 0)
            logger.info('crm_rotinas: %s', resultado)
            ciclo += 1
            for _ in range(INTERVALO_SEGUNDOS):
                if parar['sinal']:
                    break
                time.sleep(1)
        self.stdout.write('crm_rotinas: encerrado.')
