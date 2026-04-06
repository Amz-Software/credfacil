from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import FotoSession


class Command(BaseCommand):
    help = 'Remove FotoSessions expiradas (expira_em anterior ao momento atual).'

    def handle(self, *args, **options):
        qs = FotoSession.objects.filter(expira_em__lt=timezone.now())
        # remove arquivos físicos antes de deletar os registros
        for session in qs:
            if session.foto:
                session.foto.delete(save=False)
        total, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f'{total} sessão(ões) expirada(s) removida(s).'))
