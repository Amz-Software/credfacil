"""Notificações do usuário logado na API do backoffice."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from notifications.models import Notification
from rest_framework.test import APIClient

from backoffice_api.tests.fabricas import URL_CSRF, cliente_logado, criar_loja, criar_usuario
from vendas.models import Loja

URL_LISTA = '/api/bo/v1/notificacoes/'
URL_NAO_LIDAS = '/api/bo/v1/notificacoes/nao-lidas/'
URL_MARCAR_LIDAS = '/api/bo/v1/notificacoes/marcar-lidas/'
URL_MARCAR_TODAS = '/api/bo/v1/notificacoes/marcar-todas-lidas/'


def url_marcar_lida(pk: int) -> str:
    return f'/api/bo/v1/notificacoes/{pk}/marcar-lida/'


def notificar(usuario, verbo: str, *, descricao: str = '', lida: bool = False, minutos_atras: int = 0, alvo=None):
    return Notification.objects.create(
        recipient=usuario,
        actor=usuario,
        verb=verbo,
        description=descricao,
        unread=not lida,
        target=alvo,
        timestamp=timezone.now() - timedelta(minutes=minutos_atras),
    )


class ListaTests(TestCase):
    def setUp(self):
        self.user = criar_usuario('analista')
        self.outro = criar_usuario('outro')
        self.cliente = cliente_logado(self.user)

    def test_lista_so_as_notificacoes_do_usuario_no_formato_paginado(self):
        notificar(self.user, 'Nova análise', descricao='Loja Centro')
        notificar(self.outro, 'De outra pessoa')
        resposta = self.cliente.get(URL_LISTA)
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual(set(corpo), {'count', 'page', 'page_size', 'total_pages', 'results'})
        self.assertEqual(corpo['count'], 1)
        item = corpo['results'][0]
        self.assertEqual(item['titulo'], 'Nova análise')
        self.assertEqual(item['descricao'], 'Loja Centro')
        self.assertFalse(item['lida'])
        self.assertIsNone(item['target_url'])
        self.assertIn('criada_em', item)

    def test_ordena_da_mais_recente_por_padrao_e_aceita_crescente(self):
        notificar(self.user, 'antiga', minutos_atras=60)
        notificar(self.user, 'recente', minutos_atras=1)
        titulos = [n['titulo'] for n in self.cliente.get(URL_LISTA).json()['results']]
        self.assertEqual(titulos, ['recente', 'antiga'])
        crescente = self.cliente.get(URL_LISTA, {'ordenar': 'criada_em'}).json()['results']
        self.assertEqual([n['titulo'] for n in crescente], ['antiga', 'recente'])

    def test_filtra_por_lida_e_por_busca(self):
        notificar(self.user, 'Proposta criada', descricao='IMEI 123')
        notificar(self.user, 'Venda gerada', lida=True)
        nao_lidas = self.cliente.get(URL_LISTA, {'lida': 'false'}).json()
        self.assertEqual([n['titulo'] for n in nao_lidas['results']], ['Proposta criada'])
        lidas = self.cliente.get(URL_LISTA, {'lida': 'true'}).json()
        self.assertEqual([n['titulo'] for n in lidas['results']], ['Venda gerada'])
        busca = self.cliente.get(URL_LISTA, {'busca': 'imei'}).json()
        self.assertEqual(busca['count'], 1)

    def test_filtro_ou_ordenacao_invalidos_respondem_400_com_campo(self):
        resposta = self.cliente.get(URL_LISTA, {'lida': 'talvez'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('lida', resposta.json()['erro']['campos'])
        resposta = self.cliente.get(URL_LISTA, {'ordenar': 'verb'})
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('ordenar', resposta.json()['erro']['campos'])

    def test_pagina_com_page_size(self):
        for i in range(3):
            notificar(self.user, f'n{i}', minutos_atras=i)
        corpo = self.cliente.get(URL_LISTA, {'page_size': 2, 'page': 2}).json()
        self.assertEqual((corpo['count'], corpo['page'], corpo['total_pages']), (3, 2, 2))
        self.assertEqual(len(corpo['results']), 1)

    def test_target_url_vem_do_alvo_em_lote(self):
        loja = criar_loja('Centro')
        notificar(self.user, 'com alvo', alvo=loja)
        with patch.object(Loja, 'get_absolute_url', create=True, return_value=f'/lojas/detalhe/{loja.pk}/'):
            item = self.cliente.get(URL_LISTA).json()['results'][0]
        self.assertEqual(item['target_url'], f'/lojas/detalhe/{loja.pk}/')

    def test_alvo_apagado_nao_quebra_a_lista(self):
        loja = criar_loja('Temporária')
        notificar(self.user, 'alvo some', alvo=loja)
        loja.delete()
        resposta = self.cliente.get(URL_LISTA)
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.json()['results'][0]['target_url'])


class ContagemTests(TestCase):
    def test_conta_so_as_nao_lidas_do_usuario(self):
        user = criar_usuario('analista')
        notificar(user, 'a')
        notificar(user, 'b', lida=True)
        notificar(criar_usuario('outro'), 'c')
        resposta = cliente_logado(user).get(URL_NAO_LIDAS)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {'nao_lidas': 1})


class MarcacaoTests(TestCase):
    def setUp(self):
        self.user = criar_usuario('analista')
        self.outro = criar_usuario('outro')
        self.cliente = cliente_logado(self.user)

    def test_marca_uma_como_lida(self):
        notificacao = notificar(self.user, 'nova')
        resposta = self.cliente.post(url_marcar_lida(notificacao.pk))
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()['lida'])
        notificacao.refresh_from_db()
        self.assertFalse(notificacao.unread)

    def test_notificacao_de_outro_usuario_responde_404(self):
        alheia = notificar(self.outro, 'alheia')
        resposta = self.cliente.post(url_marcar_lida(alheia.pk))
        self.assertEqual(resposta.status_code, 404)
        alheia.refresh_from_db()
        self.assertTrue(alheia.unread)

    def test_mutacao_por_get_nao_e_aceita(self):
        notificacao = notificar(self.user, 'nova')
        self.assertEqual(self.cliente.get(url_marcar_lida(notificacao.pk)).status_code, 405)
        self.assertEqual(self.cliente.get(URL_MARCAR_TODAS).status_code, 405)

    def test_marca_selecionadas_ignorando_as_de_outros(self):
        minha = notificar(self.user, 'minha')
        ja_lida = notificar(self.user, 'já lida', lida=True)
        alheia = notificar(self.outro, 'alheia')
        resposta = self.cliente.post(
            URL_MARCAR_LIDAS, {'ids': [minha.pk, ja_lida.pk, alheia.pk]}, format='json'
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {'atualizadas': 1})
        alheia.refresh_from_db()
        self.assertTrue(alheia.unread)

    def test_selecao_vazia_ou_invalida_responde_400(self):
        resposta = self.cliente.post(URL_MARCAR_LIDAS, {'ids': []}, format='json')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('ids', resposta.json()['erro']['campos'])
        resposta = self.cliente.post(URL_MARCAR_LIDAS, {'ids': ['x']}, format='json')
        self.assertEqual(resposta.status_code, 400)

    def test_marca_todas_so_do_usuario(self):
        notificar(self.user, 'a')
        notificar(self.user, 'b')
        alheia = notificar(self.outro, 'c')
        resposta = self.cliente.post(URL_MARCAR_TODAS)
        self.assertEqual(resposta.json(), {'atualizadas': 2})
        self.assertEqual(self.user.notifications.unread().count(), 0)
        alheia.refresh_from_db()
        self.assertTrue(alheia.unread)


class AcessoTests(TestCase):
    def test_sem_login_responde_401(self):
        self.assertEqual(APIClient().get(URL_LISTA).status_code, 401)

    def test_post_sem_csrf_e_recusado(self):
        user = criar_usuario('analista')
        notificacao = notificar(user, 'nova')
        cliente = cliente_logado(user)
        cliente.credentials()  # remove o X-CSRFToken
        resposta = cliente.post(url_marcar_lida(notificacao.pk))
        self.assertEqual(resposta.status_code, 403)
        notificacao.refresh_from_db()
        self.assertTrue(notificacao.unread)

    def test_troca_de_senha_pendente_bloqueia_com_codigo_proprio(self):
        user = criar_usuario('antigo', senha='senhafraca')
        resposta = cliente_logado(user, senha='senhafraca').get(URL_LISTA)
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(resposta.json()['erro']['codigo'], 'troca_senha_obrigatoria')

    def test_usuario_sem_acesso_ao_backoffice_nao_entra(self):
        criar_usuario('vendedor', acesso_backoffice=False)
        cliente = APIClient(enforce_csrf_checks=True)
        cliente.get(URL_CSRF)
        self.assertEqual(cliente.get(URL_LISTA).status_code, 401)
