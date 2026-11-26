"""Gera o par de chaves VAPID do Web Push (uma vez por ambiente; guarde no .env)."""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b'=').decode()


class Command(BaseCommand):
    help = 'Gera VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY para o Web Push.'

    def handle(self, *args, **options):
        privada = ec.generate_private_key(ec.SECP256R1())
        numero_privado = privada.private_numbers().private_value.to_bytes(32, 'big')
        publica = privada.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint,
        )
        self.stdout.write('Coloque no .env do servidor (não versionar a privada):\n')
        self.stdout.write(f'VAPID_PUBLIC_KEY={_b64url(publica)}')
        self.stdout.write(f'VAPID_PRIVATE_KEY={_b64url(numero_privado)}')
        self.stdout.write('VAPID_CONTATO=mailto:suporte@centralipx.com')
