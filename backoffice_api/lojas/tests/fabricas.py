"""Dados de teste do módulo lojas."""
import io
import itertools
from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from backoffice_api.models import RegistroAuditoria
from financeiro.models import Repasse
from vendas.models import Cliente, ComprovantesCliente, Venda

URL_BASE = '/api/bo/v1/lojas/'
_sequencia = itertools.count(1)


def momento(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time(12, 0)))


def criar_venda(loja, dia: date, repasse: str = '500.00') -> Venda:
    numero = next(_sequencia)
    vendedor = get_user_model().objects.create_user(
        username=f'vend{numero}', email=f'vend{numero}@teste.local', password='x')
    cliente = Cliente.objects.create(
        nome=f'Cliente {numero}', telefone='91999999999', cpf='12345678901', nascimento=date(1990, 1, 1),
        rg='1', cep='66000000', endereco='Rua', bairro='B', cidade='Belém',
        comprovantes=ComprovantesCliente.objects.create(),
    )
    venda = Venda.objects.create(cliente=cliente, vendedor=vendedor, loja=loja, repasse_logista=Decimal(repasse))
    Venda.objects.filter(pk=venda.pk).update(data_venda=momento(dia))
    return venda


def criar_repasse(loja, dia: date, user, valor: str = '500.00', status: str = 'pendente') -> Repasse:
    return Repasse.objects.create(loja=loja, valor=Decimal(valor), data=timezone.make_aware(
        datetime.combine(dia, time.min)), status=status, criado_por=user, atualizado_por=user)


def imagem_png(nome: str = 'logo.png') -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4), 'yellow').save(buffer, format='PNG')
    return SimpleUploadedFile(nome, buffer.getvalue(), content_type='image/png')


def ultima_auditoria(acao: str):
    return RegistroAuditoria.objects.filter(acao=acao).order_by('-id').first()


def ids(resposta) -> list[int]:
    return [item['id'] for item in resposta.json()['results']]
