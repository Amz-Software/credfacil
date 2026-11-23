"""Fase 0 de segurança da API do vendedor: grupos, usuários, repasses, solicitações,
logout JWT, uploads e limite de tentativas."""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from api.models import FotoSession
from financeiro.models import Repasse
from vendas.models import AnaliseCreditoCliente, Loja, Venda
from vendas.tests_services import CenarioMixin, criar_cliente

PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)
SENHA_FORTE = 'Senha-Forte-2026!x'


def dar_permissoes(user, *codigos):
    for codigo in codigos:
        app_label, codename = codigo.split('.')
        user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
    return User.objects.get(pk=user.pk)


class GruposTests(APITestCase):
    def setUp(self):
        self.vendedor = User.objects.create_user(username='vend', email='v@t.com', password='x')
        self.grupo = Group.objects.create(name='VENDEDOR')
        self.client.force_authenticate(self.vendedor)

    def test_vendedor_lista_grupos(self):
        resposta = self.client.get('/api/grupos/')
        self.assertEqual(resposta.status_code, 200)

    def test_vendedor_nao_cria_nem_edita_grupo(self):
        todas = list(Permission.objects.values_list('id', flat=True)[:5])
        criar = self.client.post('/api/grupos/', {'name': 'X', 'permissions': todas}, format='json')
        editar = self.client.patch(f'/api/grupos/{self.grupo.pk}/', {'permissions': todas}, format='json')
        excluir = self.client.delete(f'/api/grupos/{self.grupo.pk}/')

        self.assertEqual((criar.status_code, editar.status_code, excluir.status_code), (403, 403, 403))
        self.assertEqual(self.grupo.permissions.count(), 0)

    def test_quem_tem_change_group_nao_concede_permissao_que_nao_tem(self):
        editor = dar_permissoes(self.vendedor, 'auth.change_group')
        self.client.force_authenticate(editor)
        alheia = Permission.objects.get(codename='delete_venda')

        resposta = self.client.patch(f'/api/grupos/{self.grupo.pk}/', {'permissions': [alheia.pk]}, format='json')

        self.assertEqual(resposta.status_code, 400)


class UsuariosTests(APITestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Loja A')
        self.gerente = User.objects.create_user(username='gerente', email='g@t.com', password='x', loja=self.loja)
        self.gerente = dar_permissoes(self.gerente, 'accounts.add_user', 'accounts.change_user', 'accounts.view_user')
        self.client.force_authenticate(self.gerente)

    def _criar(self, **extra):
        dados = {'username': 'novo', 'email': 'novo@t.com', 'first_name': 'Novo', 'last_name': 'Usuario',
                 'password': SENHA_FORTE, **extra}
        return self.client.post('/api/usuarios/', dados, format='json')

    def test_add_user_nao_cria_superusuario_nem_staff(self):
        resposta = self._criar(is_superuser=True, is_staff=True,
                               user_permissions=list(Permission.objects.values_list('id', flat=True)))

        self.assertEqual(resposta.status_code, 201, resposta.data)
        novo = User.objects.get(username='novo')
        self.assertEqual((novo.is_superuser, novo.is_staff, novo.user_permissions.count()), (False, False, 0))

    def test_grupo_acima_do_proprio_e_recusado(self):
        admin = Group.objects.create(name='ADMINISTRADOR')
        admin.permissions.add(Permission.objects.get(codename='delete_venda'))

        resposta = self._criar(groups=[admin.pk])

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('groups', resposta.data)

    def test_grupo_dentro_do_proprio_e_aceito(self):
        vendedor = Group.objects.create(name='VENDEDOR')
        vendedor.permissions.add(Permission.objects.get(codename='view_user'))

        resposta = self._criar(groups=[vendedor.pk])

        self.assertEqual(resposta.status_code, 201, resposta.data)

    def test_senha_fraca_e_recusada_no_campo_password(self):
        resposta = self._criar(password='123')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('password', resposta.data)

    def test_nao_edita_superusuario_da_mesma_loja(self):
        chefe = User.objects.create_superuser(username='chefe', email='c@t.com', password='x', loja=self.loja)

        resposta = self.client.patch(f'/api/usuarios/{chefe.pk}/', {'email': 'meu@t.com'}, format='json')

        self.assertEqual(resposta.status_code, 403)

    def test_superusuario_concede_qualquer_grupo(self):
        admin = Group.objects.create(name='ADMINISTRADOR')
        admin.permissions.add(Permission.objects.get(codename='delete_venda'))
        self.client.force_authenticate(User.objects.create_superuser(username='su', email='s@t.com', password='x'))

        self.assertEqual(self._criar(groups=[admin.pk]).status_code, 201)


class RepassesTests(APITestCase):
    def setUp(self):
        self.loja = Loja.objects.create(nome='Minha')
        self.outra = Loja.objects.create(nome='Outra')
        self.user = User.objects.create_user(username='fin', email='f@t.com', password='x')
        self.loja.usuarios.add(self.user)
        self.meu = self._repasse(self.loja)
        self.alheio = self._repasse(self.outra)

    def _repasse(self, loja):
        return Repasse.objects.create(loja=loja, valor='10.00', data=timezone.now(),
                                      criado_por=self.user, atualizado_por=self.user)

    def test_lista_exige_view_repasse(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get('/api/repasses/').status_code, 403)

    def test_sem_loja_lista_so_as_lojas_do_usuario(self):
        self.client.force_authenticate(dar_permissoes(self.user, 'financeiro.view_repasse'))

        ids = [r['id'] for r in self.client.get('/api/repasses/').data['results']]
        fora = self.client.get(f'/api/repasses/?loja={self.outra.pk}').data['results']

        self.assertEqual(ids, [self.meu.pk])
        self.assertEqual(fora, [])

    def test_alterar_e_excluir_exigem_permissao_e_escopo(self):
        user = dar_permissoes(self.user, 'financeiro.view_repasse', 'financeiro.change_repasse')
        self.client.force_authenticate(user)

        sem_perm = self.client.delete(f'/api/repasses/{self.meu.pk}/')
        fora = self.client.patch(f'/api/repasses/{self.alheio.pk}/', {'status': 'pago'}, format='json')
        dentro = self.client.patch(f'/api/repasses/{self.meu.pk}/', {'status': 'pago'}, format='json')

        self.assertEqual((sem_perm.status_code, fora.status_code, dentro.status_code), (403, 404, 200))

    def test_quem_ve_todas_as_lojas_lista_tudo(self):
        user = dar_permissoes(self.user, 'financeiro.view_repasse', 'vendas.can_view_all_stores')
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get('/api/repasses/').data['count'], 2)

    def test_agendados_continua_para_o_vendedor_da_loja_sem_permissao_de_repasse(self):
        self.client.force_authenticate(self.user)

        propria = self.client.get(f'/api/repasses/agendados/?loja={self.loja.pk}')
        alheia = self.client.get(f'/api/repasses/agendados/?loja={self.outra.pk}')

        self.assertEqual(propria.status_code, 200)
        self.assertEqual(propria.data['loja_id'], self.loja.pk)
        self.assertEqual(alheia.status_code, 403)


class SolicitacoesEscopoTests(CenarioMixin, APITestCase):
    def setUp(self):
        self.montar_cenario()
        Loja.objects.create(nome='CredFacil', credfacil=True)
        self.vendedor = dar_permissoes(self.vendedor, 'vendas.change_cliente', 'vendas.view_cliente', 'vendas.add_venda')
        self.outra_loja = Loja.objects.create(nome='Outra')
        self.cliente_alheio = criar_cliente(self.outra_loja, nome='Ana', cpf='99988877766')
        AnaliseCreditoCliente.objects.create(
            cliente=self.cliente_alheio, produto=self.produto, loja=self.outra_loja, status='EA',
            data_pagamento='10', numero_parcelas='10',
        )

    def _post(self, cliente, acao, dados=None):
        return self.client.post(reverse(f'solicitacao-{acao}', args=[cliente.pk]), dados or {}, format='json')

    def test_vendedor_nao_aprova_nem_reprova_com_change_cliente(self):
        self.client.force_authenticate(self.vendedor)
        self.analise.status = 'EA'
        self.analise.save()

        self.assertEqual(self._post(self.cliente, 'aprovar').status_code, 403)
        self.assertEqual(self._post(self.cliente, 'reprovar').status_code, 403)
        self.analise.refresh_from_db()
        self.assertEqual(self.analise.status, 'EA')

    def test_vendedor_age_na_propria_loja(self):
        self.client.force_authenticate(self.vendedor)

        self.assertEqual(self._post(self.cliente, 'confirmar-leitura-qrcode').status_code, 200)
        self.assertEqual(self._post(self.cliente, 'configurar-icloud', {'imei_ultimos_digitos': '1234'}).status_code, 200)
        self.assertEqual(self._post(self.cliente, 'log-consulta-serasa', {'tipo': 'serasa'}).status_code, 201)

    def test_vendedor_gera_venda_e_cancela_na_propria_loja(self):
        self.client.force_authenticate(self.vendedor)

        venda = self._post(self.cliente, 'gerar-venda')
        cancelada = self._post(self.cliente, 'cancelar')

        self.assertEqual(venda.status_code, 201, venda.data)
        self.assertEqual(cancelada.status_code, 200)

    def test_objeto_de_outra_loja_responde_404(self):
        self.client.force_authenticate(self.vendedor)

        for acao, dados in (('confirmar-app', {}), ('cancelar', {}), ('gerar-venda', {}),
                            ('configurar-icloud', {'imei_ultimos_digitos': '1234'}),
                            ('log-consulta-serasa', {'tipo': 'serasa'})):
            with self.subTest(acao=acao):
                self.assertEqual(self._post(self.cliente_alheio, acao, dados).status_code, 404)

    def test_id_inexistente_responde_404(self):
        self.client.force_authenticate(self.vendedor)
        resposta = self.client.post(reverse('solicitacao-cancelar', args=[999999]), {}, format='json')
        self.assertEqual(resposta.status_code, 404)

    def test_gerente_age_nas_lojas_que_gerencia(self):
        gerente = User.objects.create_user(username='ger', email='ger@t.com', password='x')
        self.outra_loja.gerentes.add(gerente)
        gerente = dar_permissoes(gerente, 'vendas.change_cliente')
        self.client.force_authenticate(gerente)

        self.assertEqual(self._post(self.cliente_alheio, 'confirmar-app').status_code, 200)
        self.assertEqual(self._post(self.cliente, 'confirmar-app').status_code, 404)

    def test_analista_com_change_status_analise_aprova(self):
        analista = dar_permissoes(self.analista, 'vendas.change_status_analise')
        self.client.force_authenticate(analista)
        self.analise.status = 'EA'
        self.analise.save()

        self.assertEqual(self._post(self.cliente, 'aprovar').status_code, 200)
        self.assertEqual(self._post(self.cliente_alheio, 'aprovar').status_code, 404)

    def test_administrador_alcanca_todas_as_lojas(self):
        admin = User.objects.create_superuser(username='adm', email='adm@t.com', password='x')
        self.client.force_authenticate(admin)

        self.assertEqual(self._post(self.cliente_alheio, 'reprovar').status_code, 200)


class LogoutJwtTests(APITestCase):
    def test_logout_invalida_o_refresh(self):
        user = User.objects.create_user(username='u', email='u@t.com', password='x')
        refresh = str(RefreshToken.for_user(user))

        logout = self.client.post('/api/token/logout/', {'refresh': refresh}, format='json')
        renovar = self.client.post('/api/token/refresh/', {'refresh': refresh}, format='json')

        self.assertEqual(logout.status_code, 200)
        self.assertEqual(renovar.status_code, 401)

    def test_logout_com_token_invalido_responde_401(self):
        self.assertEqual(self.client.post('/api/token/logout/', {'refresh': 'x'}, format='json').status_code, 401)


class UploadTests(CenarioMixin, APITestCase):
    def setUp(self):
        self.montar_cenario()
        self.vendedor = dar_permissoes(self.vendedor, 'vendas.change_venda', 'vendas.view_venda')
        self.loja.usuarios.add(self.vendedor)
        self.venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=self.loja,
                                          repasse_logista=Decimal('0'))
        self.client.force_authenticate(self.vendedor)

    def test_documento_da_venda_recusa_html_disfarcado_de_imagem(self):
        falso = SimpleUploadedFile('foto.png', b'<html><script>alert(1)</script></html>', content_type='image/png')

        resposta = self.client.post(f'/api/vendas/{self.venda.pk}/documentos/', {'foto_cliente': falso})

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('foto_cliente', resposta.data['errors'])

    def test_documento_da_venda_recusa_acima_de_10mb(self):
        grande = SimpleUploadedFile('c.pdf', b'%PDF' + b'0' * (10 * 1024 * 1024), content_type='application/pdf')

        resposta = self.client.post(f'/api/vendas/{self.venda.pk}/documentos/', {'documento_assinado': grande})

        self.assertEqual(resposta.status_code, 400)

    def test_solicitacao_recusa_arquivo_invalido(self):
        vendedor = dar_permissoes(self.vendedor, 'vendas.change_cliente')
        self.client.force_authenticate(vendedor)
        falso = SimpleUploadedFile('rg.jpg', b'MZ\x90\x00executavel', content_type='image/jpeg')

        resposta = self.client.patch(f'/api/solicitacoes/{self.cliente.pk}/', {'foto_cliente': falso})

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('foto_cliente', resposta.data['errors'])

    def test_foto_session_ignora_content_type_do_cliente(self):
        sessao = FotoSession.objects.create(expira_em=timezone.now() + timezone.timedelta(minutes=5))
        falso = SimpleUploadedFile('f.jpg', b'%PDF-1.4 nao e imagem', content_type='image/jpeg')

        resposta = self.client.post(f'/api/foto-upload/{sessao.session_id}/', {'foto': falso})

        self.assertEqual(resposta.status_code, 400)

    def test_foto_session_aceita_png(self):
        sessao = FotoSession.objects.create(expira_em=timezone.now() + timezone.timedelta(minutes=5))
        with override_settings(STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        }):
            resposta = self.client.post(f'/api/foto-upload/{sessao.session_id}/',
                                        {'foto': SimpleUploadedFile('f.png', PNG, content_type='image/png')})
        self.assertEqual(resposta.status_code, 200)


class LimiteDeTentativasApiTests(APITestCase):
    TAXAS = {'anon': '1000/min', 'user': '1000/min', 'login': '2/min', 'publico': '2/min'}

    def setUp(self):
        cache.clear()
        patcher = mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', self.TAXAS)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(cache.clear)

    def test_buscar_lojas_responde_igual_para_inexistente_e_limita_por_ip(self):
        primeira = self.client.get('/api/buscar-lojas/?username=ninguem')
        self.client.get('/api/buscar-lojas/?username=ninguem')
        terceira = self.client.get('/api/buscar-lojas/?username=ninguem')

        self.assertEqual((primeira.status_code, primeira.data), (200, {'lojas': []}))
        self.assertEqual(terceira.status_code, 429)

    def test_token_limitado_no_escopo_login(self):
        for _ in range(2):
            self.client.post('/api/token/', {'username': 'x', 'password': 'y'}, format='json')
        self.assertEqual(self.client.post('/api/token/', {'username': 'x', 'password': 'y'}).status_code, 429)

    def test_contrato_publico_limitado(self):
        url = '/api/contrato/00000000-0000-4000-8000-000000000000/'
        self.client.get(url)
        self.client.get(url)
        self.assertEqual(self.client.get(url).status_code, 429)
