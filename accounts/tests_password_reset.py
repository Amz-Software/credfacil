"""Recuperação de senha por e-mail e troca de senha pelo perfil."""
import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

NOVA_SENHA = 'Nova-Senha-Forte-2026'


class RecuperarSenhaPorEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='maria', email='maria@teste.com', password='antiga-123')

    def _link_do_email(self) -> str:
        resposta = self.client.post(reverse('accounts:password_reset'), {'email': 'maria@teste.com'})
        self.assertRedirects(resposta, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        return re.search(r'https?://[^/\s]+(/reset/\S+/)', mail.outbox[0].body).group(1)

    def test_fluxo_completo_define_a_nova_senha(self):
        link = self._link_do_email()

        # O Django troca o token da URL pela sessão e redireciona para .../set-password/.
        tela = self.client.get(link, follow=True)
        self.assertContains(tela, 'Definir nova senha')
        resposta = self.client.post(tela.redirect_chain[-1][0], {
            'new_password1': NOVA_SENHA, 'new_password2': NOVA_SENHA,
        })

        self.assertRedirects(resposta, reverse('accounts:password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NOVA_SENHA))
        self.assertContains(self.client.get(reverse('accounts:password_reset_complete')), 'Senha Redefinida')

    def test_pagina_de_email_enviado_explica_o_proximo_passo(self):
        self.assertContains(self.client.get(reverse('accounts:password_reset_done')), 'Verifique seu e-mail')

    def test_link_invalido_oferece_novo_pedido(self):
        resposta = self.client.get(reverse('accounts:password_reset_confirm', args=['MQ', 'token-invalido']))

        self.assertContains(resposta, 'Link inválido ou expirado')
        self.assertContains(resposta, reverse('accounts:password_reset'))


class TrocarSenhaPeloPerfilTests(TestCase):
    def test_troca_e_continua_logado(self):
        user = User.objects.create_user(username='joao', email='joao@teste.com', password='antiga-123')
        self.client.force_login(user)

        resposta = self.client.post(reverse('accounts:resetar_senha'), {
            'password': NOVA_SENHA, 'password_confirm': NOVA_SENHA,
        })

        self.assertRedirects(resposta, reverse('accounts:my_profile_update'))
        user.refresh_from_db()
        self.assertTrue(user.check_password(NOVA_SENHA))
        self.assertEqual(self.client.get(reverse('accounts:my_profile_update')).status_code, 200)
