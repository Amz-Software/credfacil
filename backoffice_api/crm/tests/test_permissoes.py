"""Permissões do CRM na API: `crm.acessar_crm` em tudo, `crm.gerenciar_crm` na configuração."""
from rest_framework.test import APIClient

from crm.models import Conversa, Mensagem

from .base import CrmApiTestCase, url


class AcessoTests(CrmApiTestCase):
    def setUp(self):
        super().setUp()
        self.conversa = self.conversa_com_humano()
        self.mensagem = Mensagem.objects.filter(conversa=self.conversa).first()

    def _rotas_do_atendente(self) -> list[tuple[str, str]]:
        c, m = self.conversa.pk, self.mensagem.pk
        return [
            ('get', 'contexto/'), ('get', 'etiquetas/'), ('get', 'respostas-rapidas/'), ('get', 'aberturas/'),
            ('get', 'atendentes/'), ('get', 'conversas/'), ('get', f'conversas/{c}/'),
            ('get', f'conversas/{c}/mensagens/'), ('post', f'conversas/{c}/ler/'), ('post', 'conversas/iniciar/'),
            ('post', f'conversas/{c}/assumir/'), ('post', f'conversas/{c}/puxar/'),
            ('post', f'conversas/{c}/atribuir/'), ('post', f'conversas/{c}/devolver/'),
            ('post', f'conversas/{c}/situacao/'), ('post', f'conversas/{c}/etiquetas/'),
            ('post', f'conversas/{c}/apelido/'), ('post', f'conversas/{c}/vincular-cliente/'),
            ('post', f'conversas/{c}/desvincular-cliente/'), ('post', f'conversas/{c}/abrir/'),
            ('post', f'conversas/{c}/enviar/'), ('post', f'conversas/{c}/digitando/'),
            ('post', f'conversas/{c}/notas/'), ('post', f'conversas/{c}/lembrete/'),
            ('post', f'conversas/{c}/lembrete/concluir/'), ('post', f'conversas/{c}/programadas/'),
            ('post', f'mensagens/{m}/reenviar/'), ('post', f'mensagens/{m}/reagir/'),
            ('get', f'mensagens/{m}/arquivo/'), ('post', 'programadas/1/cancelar/'),
            ('get', f'conversas/{c}/respostas-rapidas/1/previa/'),
        ]

    def test_sem_acessar_crm_recebe_403_em_tudo(self):
        api = self.api(self.sem_acesso)
        for metodo, caminho in self._rotas_do_atendente():
            with self.subTest(rota=caminho, metodo=metodo):
                resposta = getattr(api, metodo)(url(caminho), {}, format='json')
                self.assertEqual(resposta.status_code, 403)
                self.assertEqual(self.erro(resposta)['codigo'], 'proibido')
                self.assertIn('CRM', self.erro(resposta)['mensagem'])
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.assumida_por, self.atendente)

    def test_sem_login_recebe_401(self):
        resposta = APIClient().get(url('conversas/'))

        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(self.erro(resposta)['codigo'], 'nao_autenticado')

    def test_sessao_das_telas_antigas_nao_vale_na_api(self):
        from backoffice_api.tests.fabricas import criar_usuario

        so_crm = criar_usuario('socrm', permissoes=('crm.acessar_crm',), acesso_backoffice=False)
        cliente = APIClient(enforce_csrf_checks=True)
        cliente.force_login(so_crm)  # sessão das telas antigas: não vale na API nova

        self.assertEqual(cliente.get(url('conversas/')).status_code, 401)

    def test_superusuario_acessa(self):
        from backoffice_api.tests.fabricas import criar_usuario

        admin = criar_usuario('raiz', superuser=True)

        self.assertEqual(self.api(admin).get(url('conversas/')).status_code, 200)
        self.assertEqual(self.api(admin).get(url('configuracao/')).status_code, 200)

    def test_acoes_nao_aceitam_get(self):
        c = self.conversa.pk
        api = self.api(self.outro)
        for caminho in ('assumir/', 'puxar/', 'devolver/', 'situacao/', 'ler/', 'enviar/', 'notas/', 'abrir/'):
            with self.subTest(acao=caminho):
                resposta = api.get(url(f'conversas/{c}/{caminho}'))
                self.assertEqual(resposta.status_code, 405)
                self.assertEqual(self.erro(resposta)['codigo'], 'metodo_nao_permitido')
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.assumida_por, self.atendente)

    def test_leituras_nao_aceitam_post(self):
        resposta = self.api().post(url(f'conversas/{self.conversa.pk}/'), {}, format='json')

        self.assertEqual(resposta.status_code, 405)

    def test_conversa_inexistente_recebe_404(self):
        resposta = self.api().get(url('conversas/999999/'))

        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(self.erro(resposta)['codigo'], 'nao_encontrado')


class GerenciaTests(CrmApiTestCase):
    ROTAS = (
        ('get', 'configuracao/'), ('patch', 'configuracao/'), ('get', 'configuracao/etiquetas/'),
        ('post', 'configuracao/etiquetas/'), ('get', 'configuracao/etiquetas/1/'),
        ('patch', 'configuracao/etiquetas/1/'), ('get', 'configuracao/respostas-rapidas/'),
        ('post', 'configuracao/respostas-rapidas/'), ('get', 'configuracao/aberturas/'),
        ('post', 'configuracao/aberturas/'), ('get', 'configuracao/aberturas/1/'),
        ('patch', 'configuracao/aberturas/1/'), ('post', 'configuracao/aberturas/1/verificar/'),
        ('post', 'configuracao/aberturas/1/simular/'), ('get', 'configuracao/simulador/'),
        ('post', 'configuracao/simulador/receber/'), ('post', 'configuracao/simulador/ler/'),
    )

    def test_configuracao_sem_gerenciar_recebe_403(self):
        api = self.api(self.atendente)
        for metodo, caminho in self.ROTAS:
            with self.subTest(rota=caminho, metodo=metodo):
                resposta = getattr(api, metodo)(url(caminho), {}, format='json')
                self.assertEqual(resposta.status_code, 403)
                self.assertEqual(self.erro(resposta)['mensagem'], 'Só quem gerencia o CRM pode fazer isso.')

    def test_gerenciar_sem_acessar_nao_vale(self):
        from backoffice_api.tests.fabricas import criar_usuario

        so_gerenciar = criar_usuario('sogerente', permissoes=('crm.gerenciar_crm',))

        self.assertEqual(self.api(so_gerenciar).get(url('configuracao/')).status_code, 403)

    def test_quem_gerencia_acessa_a_configuracao(self):
        api = self.api(self.gestor)
        for caminho in ('configuracao/', 'configuracao/etiquetas/', 'configuracao/respostas-rapidas/',
                        'configuracao/aberturas/', 'configuracao/simulador/'):
            with self.subTest(rota=caminho):
                self.assertEqual(api.get(url(caminho)).status_code, 200)


class PermissoesDeOutrosDominiosTests(CrmApiTestCase):
    def test_busca_de_cliente_exige_view_cliente(self):
        self.assertEqual(self.api().get(url('clientes/'), {'busca': 'Maria'}).status_code, 403)
        atendente = self.dar_permissao(self.atendente, 'vendas.view_cliente')
        self.assertEqual(self.api(atendente).get(url('clientes/'), {'busca': 'Maria'}).status_code, 200)

    def test_resumo_de_pagamentos_exige_view_pagamento(self):
        conversa = self.receber('Oi').conversa

        resposta = self.api().get(url(f'conversas/{conversa.pk}/resumo-pagamentos/'), {'cliente': 1})

        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(Conversa.objects.count(), 1)
