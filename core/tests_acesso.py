"""Testes de controle de acesso do backoffice.

Cobrem três garantias:
1. Nenhuma tela do backoffice abre sem login, exceto a lista explícita de
   páginas públicas.
2. Telas de usuários/grupos/permissões exigem a permissão declarada.
3. Ações destrutivas só aceitam POST e exigem permissão.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from vendas.models import Cliente, ComprovantesCliente, Loja, Venda


def _criar_venda(loja: Loja, vendedor: User) -> Venda:
    cliente = Cliente.objects.create(
        nome='Cliente Teste', telefone='91999999999', cpf='12345678900',
        nascimento=date(1990, 1, 1), rg='123', cep='66000000',
        endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(loja=loja),
    )
    return Venda.objects.create(
        cliente=cliente, vendedor=vendedor, loja=loja,
        repasse_logista=Decimal('100.00'),
    )


class AcessoBaseTestCase(TestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja Acesso')
        self.user = User.objects.create_user(
            username='semperm', email='semperm@example.com', password='123456',
        )
        self.loja.usuarios.add(self.user)
        self.venda = _criar_venda(self.loja, self.user)

    def _login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['loja_id'] = self.loja.id
        session.save()

    def _add_perm(self, app_label: str, codename: str):
        perm = Permission.objects.get(
            content_type__app_label=app_label, codename=codename,
        )
        self.user.user_permissions.add(perm)
        # Limpa o cache de permissões do objeto em memória.
        self.user = User.objects.get(pk=self.user.pk)

    def _assert_redireciona_para_login(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith(reverse('accounts:login')),
            f'Esperava redirecionar para o login, foi para {response.url}',
        )


class AnonimoNaoAcessaBackofficeTests(AcessoBaseTestCase):
    def test_telas_protegidas_redirecionam_anonimo_para_login(self):
        urls = [
            reverse('vendas:index'),
            reverse('vendas:grafico'),
            reverse('vendas:venda_cancel', args=[self.venda.id]),
            reverse('vendas:gerar_contrato', args=[self.venda.id]),
            reverse('vendas:gerar_carne', args=[self.venda.id, 'carne']),
            reverse('vendas:loja_replicar', args=[self.loja.id]),
            reverse('vendas:cliente_edit_form'),
            reverse('vendas:info_produto'),
            reverse('vendas:payment_data'),
            reverse('vendas:produtos_ajax'),
            reverse('accounts:user_list'),
            reverse('accounts:user_create'),
            reverse('accounts:user_update', args=[self.user.id]),
            reverse('accounts:user_delete', args=[self.user.id]),
            reverse('accounts:group_list'),
            reverse('accounts:group_create'),
            reverse('accounts:permissions_list'),
            reverse('accounts:profile'),
            reverse('accounts:password_reset_confirm'),
            reverse('accounts:autorizacao_user'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self._assert_redireciona_para_login(self.client.get(url))

    def test_anonimo_nao_cancela_venda(self):
        url = reverse('vendas:venda_cancel', args=[self.venda.id])

        self.client.get(url)
        self.client.post(url)

        self.venda.refresh_from_db()
        self.assertFalse(self.venda.is_deleted)

    def test_anonimo_nao_desativa_usuario(self):
        url = reverse('accounts:user_delete', args=[self.user.id])

        self.client.post(url)

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_paginas_publicas_continuam_abertas(self):
        casos = [
            (reverse('accounts:login'), 200),
            (reverse('accounts:password_reset'), 200),
            (reverse('vendas:consulta_pagamentos'), 200),
            # Sem username a view responde 400, mas não exige login.
            (reverse('accounts:buscar_lojas'), 400),
        ]
        for url, status_esperado in casos:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, status_esperado)

    def test_api_nao_e_redirecionada_para_login_do_backoffice(self):
        response = self.client.get('/api/health/')

        self.assertNotEqual(response.status_code, 302)


class TelasDeUsuariosExigemPermissaoTests(AcessoBaseTestCase):
    def test_usuario_sem_permissao_recebe_403(self):
        self._login()
        urls = [
            reverse('accounts:user_list'),
            reverse('accounts:user_create'),
            reverse('accounts:user_update', args=[self.user.id]),
            reverse('accounts:group_list'),
            reverse('accounts:group_create'),
            reverse('accounts:permissions_list'),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_usuario_com_permissao_abre_lista_de_usuarios(self):
        self._add_perm('accounts', 'view_user')
        self._login()

        response = self.client.get(reverse('accounts:user_list'))

        self.assertEqual(response.status_code, 200)

    def test_desativar_usuario_exige_permissao(self):
        alvo = User.objects.create_user(
            username='alvo', email='alvo@example.com', password='123456',
        )
        self._login()

        response = self.client.post(reverse('accounts:user_delete', args=[alvo.id]))

        self.assertEqual(response.status_code, 403)
        alvo.refresh_from_db()
        self.assertTrue(alvo.is_active)

    def test_desativar_usuario_com_permissao_via_post(self):
        alvo = User.objects.create_user(
            username='alvo', email='alvo@example.com', password='123456',
        )
        self._add_perm('accounts', 'delete_user')
        self._login()
        url = reverse('accounts:user_delete', args=[alvo.id])

        resposta_get = self.client.get(url)
        alvo.refresh_from_db()
        ativo_apos_get = alvo.is_active
        self.client.post(url)
        alvo.refresh_from_db()

        self.assertEqual(resposta_get.status_code, 405)
        self.assertTrue(ativo_apos_get)
        self.assertFalse(alvo.is_active)


class AcoesDestrutivasTests(AcessoBaseTestCase):
    def test_cancelar_venda_sem_permissao_recebe_403(self):
        self._login()

        response = self.client.post(reverse('vendas:venda_cancel', args=[self.venda.id]))

        self.assertEqual(response.status_code, 403)
        self.venda.refresh_from_db()
        self.assertFalse(self.venda.is_deleted)

    def test_cancelar_venda_nao_aceita_get(self):
        self._add_perm('vendas', 'delete_venda')
        self._login()

        response = self.client.get(reverse('vendas:venda_cancel', args=[self.venda.id]))

        self.assertEqual(response.status_code, 405)
        self.venda.refresh_from_db()
        self.assertFalse(self.venda.is_deleted)

    def test_cancelar_venda_com_permissao_via_post(self):
        self._add_perm('vendas', 'delete_venda')
        self._login()

        self.client.post(reverse('vendas:venda_cancel', args=[self.venda.id]))

        self.venda.refresh_from_db()
        self.assertTrue(self.venda.is_deleted)

    def test_replicar_qrcode_exige_permissao_e_post(self):
        outra = Loja.objects.create(nome='Outra Loja')
        self.loja.codigo_aplicativo = '1234'
        self.loja.qr_code_aplicativo = 'qr_codes_aplicativo/origem.png'
        self.loja.save()
        url = reverse('vendas:loja_replicar', args=[self.loja.id])
        self._login()

        sem_permissao = self.client.post(url)
        self._add_perm('vendas', 'change_loja')
        self._login()
        via_get = self.client.get(url)
        outra.refresh_from_db()
        codigo_apos_get = outra.codigo_aplicativo
        self.client.post(url)
        outra.refresh_from_db()

        self.assertEqual(sem_permissao.status_code, 403)
        self.assertEqual(via_get.status_code, 405)
        self.assertIsNone(codigo_apos_get)
        self.assertEqual(outra.codigo_aplicativo, '1234')

    def test_grafico_exige_permissao_de_dashboard(self):
        self._login()

        response = self.client.get(reverse('vendas:grafico'))

        self.assertEqual(response.status_code, 403)

    def test_contrato_e_carne_exigem_permissao_de_ver_venda(self):
        self._login()
        urls = [
            reverse('vendas:gerar_contrato', args=[self.venda.id]),
            reverse('vendas:gerar_carne', args=[self.venda.id, 'carne']),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_telas_usam_confirmacao_por_post_nas_acoes_destrutivas(self):
        admin = User.objects.create_superuser(
            username='admin', email='admin@example.com', password='123456',
        )
        self.loja.usuarios.add(admin)
        self.user = admin
        self._login()
        casos = [
            (reverse('vendas:venda_detail', args=[self.venda.id]),
             reverse('vendas:venda_cancel', args=[self.venda.id])),
            (reverse('vendas:loja_list'),
             reverse('vendas:loja_replicar', args=[self.loja.id])),
        ]

        for tela, acao in casos:
            with self.subTest(tela=tela):
                response = self.client.get(tela)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-post-url="{acao}"')
                self.assertNotContains(response, f'href="{acao}"')
                self.assertContains(response, 'id="confirmActionModal"')

    def test_reprovar_e_cancelar_analise_nao_aceitam_get(self):
        self._add_perm('vendas', 'change_status_analise')
        self._add_perm('vendas', 'change_analisecreditocliente')
        self._login()
        urls = [
            reverse('vendas:reprovar_analise', args=[999999]),
            reverse('vendas:cancelar_analise', args=[999999]),
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
