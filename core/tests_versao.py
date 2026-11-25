"""Aviso de nova versão: versão lida do .git, rota sem cache e aviso na página."""
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from accounts.models import User
from core import versao

COMMIT_ANTIGO = 'a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0'
COMMIT_NOVO = 'f0e1d2c3b4a5f6e7d8c9b0a1f2e3d4c5b6a7f8e9'


class VersaoTests(TestCase):
    def setUp(self):
        versao.versao_atual.cache_clear()
        self.addCleanup(versao.versao_atual.cache_clear)
        self.pasta = Path(tempfile.mkdtemp(prefix='versao-'))
        (self.pasta / '.git' / 'refs' / 'heads').mkdir(parents=True)
        (self.pasta / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
        semente = mock.patch.dict(os.environ, {'APP_VERSAO': ''})
        semente.start()
        self.addCleanup(semente.stop)

    def _versao(self) -> str:
        versao.versao_atual.cache_clear()
        with override_settings(BASE_DIR=self.pasta):
            return versao.versao_atual()

    def test_le_o_commit_da_ref_solta_e_do_packed_refs(self):
        (self.pasta / '.git' / 'packed-refs').write_text(f'# pack-refs\n{COMMIT_ANTIGO} refs/heads/main\n')
        self.assertEqual(self._versao(), COMMIT_ANTIGO[:versao.TAMANHO_VERSAO])

        (self.pasta / '.git' / 'refs' / 'heads' / 'main').write_text(f'{COMMIT_NOVO}\n')
        self.assertEqual(self._versao(), COMMIT_NOVO[:versao.TAMANHO_VERSAO])

    def test_variavel_de_ambiente_tem_prioridade_e_sem_git_vira_dev(self):
        with mock.patch.dict(os.environ, {'APP_VERSAO': 'build-42'}):
            self.assertEqual(self._versao(), 'build-42')
        (self.pasta / '.git' / 'HEAD').unlink()
        self.assertEqual(self._versao(), versao.SEM_VERSAO)

    def test_rota_sem_cache_so_para_quem_esta_logado(self):
        anonimo = self.client.get('/versao/')
        usuario = User.objects.create_user(username='ana', email='ana@example.com', password='x')
        self.client.force_login(usuario)
        logado = self.client.get('/versao/')

        self.assertEqual(anonimo.status_code, 302)  # LoginObrigatorioMiddleware manda para o login
        self.assertEqual(logado.status_code, 200)
        self.assertEqual(logado.json()['versao'], versao.versao_atual())
        self.assertEqual(logado['Cache-Control'], 'no-store')

    def test_pagina_traz_o_aviso_com_a_versao(self):
        usuario = User.objects.create_superuser(username='adm', email='adm@example.com', password='x')
        self.client.force_login(usuario)

        pagina = self.client.get('/crm/')

        self.assertContains(pagina, 'id="avisoNovaVersao"')
        self.assertContains(pagina, f'data-versao="{versao.versao_atual()}"')
        self.assertContains(pagina, 'js/versao.js')
