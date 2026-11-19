"""Base dos testes do CRM: WhatsApp simulado, tarefas síncronas, usuários com e sem permissão."""
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from crm.models import Conversa
from crm.services.conversas import EntradaNormalizada, receber_mensagem

SEM_META = {chave: '' for chave in (
    'WHATSAPP_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_WABA_ID', 'WHATSAPP_APP_SECRET', 'WHATSAPP_VERIFY_TOKEN',
)}


@override_settings(CRM_TAREFAS_SINCRONAS=True, NOTIFICACAO_WS_SINCRONO=False)
class CrmTestCase(TestCase):
    def setUp(self):
        self.pasta_midia = tempfile.mkdtemp(prefix='crm-testes-')
        self.addCleanup(shutil.rmtree, self.pasta_midia, ignore_errors=True)
        midia = override_settings(CRM_MIDIA_ROOT=self.pasta_midia, MEDIA_ROOT=self.pasta_midia)
        midia.enable()
        self.addCleanup(midia.disable)
        self.env = mock.patch.dict(os.environ, SEM_META)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ws = mock.patch('notificacao.utils._despachar')
        self.ws.start()
        self.addCleanup(self.ws.stop)
        self.atendente = self.criar_usuario('ana', acessar=True)
        self.outro = self.criar_usuario('bruno', acessar=True)
        self.gestor = self.criar_usuario('carla', acessar=True, gerenciar=True)
        self.sem_acesso = self.criar_usuario('davi')

    def criar_usuario(self, username: str, acessar: bool = False, gerenciar: bool = False, **extra) -> User:
        usuario = User.objects.create_user(username=username, email=f'{username}@example.com', password='123456',
                                           first_name=username.capitalize(), **extra)
        codigos = [c for c, ligado in (('acessar_crm', acessar), ('gerenciar_crm', gerenciar)) if ligado]
        if codigos:
            usuario.user_permissions.add(*Permission.objects.filter(content_type__app_label='crm', codename__in=codigos))
        return User.objects.get(pk=usuario.pk)

    def criar_usuario_recarregado(self, usuario) -> User:
        return User.objects.get(pk=usuario.pk)  # descarta o cache de permissões

    def api(self, usuario) -> APIClient:
        cliente = APIClient()
        cliente.force_authenticate(usuario)
        return cliente

    def receber(self, texto: str = 'Olá', telefone: str = '5591999990000', wamid: str | None = None, **extra):
        with self.captureOnCommitCallbacks(execute=True):
            return receber_mensagem(EntradaNormalizada(
                telefone=telefone, wa_message_id=wamid or f'wamid.{timezone.now().timestamp()}.{texto}',
                tipo=extra.pop('tipo', 'TEXTO'), texto=texto, contato_nome=extra.pop('nome', 'Maria Souza'), **extra,
            ))

    def conversa_com_humano(self, usuario=None) -> Conversa:
        conversa = self.receber('Quero saber da minha proposta').conversa
        conversa.modo, conversa.assumida_por = Conversa.Modo.HUMANO, usuario or self.atendente
        conversa.assumida_em = timezone.now()
        conversa.save()
        return conversa

    @contextmanager
    def em_commit(self):
        with self.captureOnCommitCallbacks(execute=True):
            yield


def fechar_janela(conversa: Conversa) -> None:
    Conversa.objects.filter(pk=conversa.pk).update(ultima_entrada_em=timezone.now() - timedelta(hours=25))
    conversa.refresh_from_db()
