"""Lista com filtros e contadores, detalhe, leitura, cursor de mensagens e nova conversa."""
from crm.models import Conversa, Mensagem

from .base import CrmApiTestCase, url


class ListaTests(CrmApiTestCase):
    def test_filas_contadores_e_campos_do_item(self):
        self.receber('Oi', telefone='5591999990001')
        self.conversa_com_humano()
        api = self.api()

        minhas = api.get(url('conversas/'), {'fila': 'minhas'}).json()
        sem_dono = api.get(url('conversas/'), {'fila': 'sem_dono'}).json()

        self.assertEqual(minhas['count'], 1)
        self.assertEqual(sem_dono['count'], 1)
        self.assertEqual(minhas['contadores'], {'minhas': 1, 'sem_dono': 1, 'automatico': 0, 'todas': 2})
        item = sem_dono['results'][0]
        self.assertEqual(item['modo'], 'AGUARDANDO')
        self.assertTrue(item['janela']['aberta'])
        self.assertIsNotNone(item['motivo_transferencia'])
        self.assertEqual(item['ultima_mensagem']['direcao'], 'SAIDA')  # boas-vindas automática
        self.assertEqual(item['telefone_formatado'], '+55 (91) 99999-0001')
        self.assertNotIn('clientes', item)  # nomes de clientes só no painel (escopo de lojas)

    def test_busca_por_texto_e_telefone(self):
        self.receber('Quero um iPhone 15', telefone='5591988887777')
        self.receber('Outra coisa', telefone='5591911112222')
        api = self.api()

        por_texto = api.get(url('conversas/'), {'fila': 'todas', 'busca': 'iphone'}).json()
        por_telefone = api.get(url('conversas/'), {'fila': 'todas', 'busca': '88887777'}).json()

        self.assertEqual((por_texto['count'], por_telefone['count']), (1, 1))

    def test_filtros_nao_lidas_situacao_e_ordem(self):
        self.receber('Oi', telefone='5591999990001')
        conversa = self.receber('Oi', telefone='5591999990002').conversa
        Conversa.objects.filter(pk=conversa.pk).update(nao_lidas=0, situacao='RESOLVIDA')
        api = self.api()

        nao_lidas = api.get(url('conversas/'), {'fila': 'todas', 'nao_lidas': 'true'}).json()
        resolvidas = api.get(url('conversas/'), {'fila': 'todas', 'situacao': 'RESOLVIDA'}).json()
        espera = api.get(url('conversas/'), {'fila': 'todas', 'ordenar': 'espera'})

        self.assertEqual(nao_lidas['count'], 1)
        self.assertEqual([c['id'] for c in resolvidas['results']], [conversa.pk])
        self.assertEqual(espera.status_code, 200)

    def test_paginacao(self):
        for final in range(3):
            self.receber('Oi', telefone=f'559199999000{final}')

        pagina = self.api().get(url('conversas/'), {'fila': 'todas', 'page_size': 2, 'page': 2}).json()

        self.assertEqual((pagina['count'], pagina['total_pages'], len(pagina['results'])), (3, 2, 1))

    def test_filtro_invalido_recebe_400_com_campos(self):
        resposta = self.api().get(url('conversas/'), {'fila': 'outra', 'ordenar': 'nome'})

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(set(self.erro(resposta)['campos']), {'fila', 'ordenar'})


class ConversaTests(CrmApiTestCase):
    def test_detalhe_nao_marca_como_lida_e_mostra_bloqueio(self):
        conversa = self.receber('Oi').conversa

        detalhe = self.api().get(url(f'conversas/{conversa.pk}/')).json()

        conversa.refresh_from_db()
        self.assertEqual(conversa.nao_lidas, 1)
        self.assertEqual(detalhe['bloqueio']['motivo'], 'NAO_ASSUMIDA')
        self.assertFalse(detalhe['pode_responder'])
        self.assertTrue(detalhe['acoes']['assumir'])
        self.assertFalse(detalhe['acoes']['puxar'])
        self.assertEqual(len(detalhe['notas']), 1)  # nota de transferência
        self.assertEqual(detalhe['painel'], {'clientes': [], 'sugeridos': []})
        self.assertEqual(detalhe['programadas'], [])

    def test_ler_zera_nao_lidas_e_manda_recibo(self):
        conversa = self.receber('Oi').conversa

        with self.em_commit():
            resposta = self.api().post(url(f'conversas/{conversa.pk}/ler/'))

        conversa.refresh_from_db()
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual((resposta.json()['nao_lidas'], conversa.nao_lidas), (0, 0))
        entrada = Mensagem.objects.get(conversa=conversa, direcao='ENTRADA')
        self.assertIsNotNone(entrada.lida_em)

    def test_detalhe_para_quem_nao_e_dono(self):
        conversa = self.conversa_com_humano(self.outro)

        detalhe = self.api().get(url(f'conversas/{conversa.pk}/')).json()

        self.assertEqual(detalhe['bloqueio']['motivo'], 'OUTRO_DONO')
        self.assertTrue(detalhe['acoes']['puxar'])
        self.assertFalse(detalhe['acoes']['atribuir'])
        self.assertEqual(detalhe['assumida_por']['id'], self.outro.pk)


class MensagensTests(CrmApiTestCase):
    def test_cursor_volta_no_tempo_sem_repetir(self):
        conversa = self.conversa_com_humano()
        for i in range(60):
            Mensagem.objects.create(conversa=conversa, direcao='SAIDA', autor='HUMANO', texto=f'm{i}',
                                    status='ENVIADO')
        total = Mensagem.objects.filter(conversa=conversa).count()
        api = self.api()

        primeira = api.get(url(f'conversas/{conversa.pk}/mensagens/')).json()
        segunda = api.get(url(f'conversas/{conversa.pk}/mensagens/'),
                          {'antes': primeira['proximo_cursor']}).json()

        self.assertEqual(len(primeira['results']), 50)
        self.assertTrue(primeira['tem_mais_antigas'])
        self.assertEqual(primeira['results'][-1]['texto'], 'm59')  # ordem cronológica
        self.assertEqual(primeira['proximo_cursor'], primeira['results'][0]['id'])
        self.assertFalse(segunda['tem_mais_antigas'])
        self.assertIsNone(segunda['proximo_cursor'])
        ids = [m['id'] for m in segunda['results'] + primeira['results']]
        self.assertEqual((len(ids), len(set(ids))), (total, total))

    def test_limite_e_cursor_invalidos(self):
        conversa = self.conversa_com_humano()
        outra = self.receber('Oi', telefone='5591988880000').conversa
        alheia = Mensagem.objects.filter(conversa=outra).first()
        api = self.api()

        limite = api.get(url(f'conversas/{conversa.pk}/mensagens/'), {'limite': 500})
        cursor = api.get(url(f'conversas/{conversa.pk}/mensagens/'), {'antes': alheia.pk})
        pequeno = api.get(url(f'conversas/{conversa.pk}/mensagens/'), {'limite': 1}).json()

        self.assertEqual((limite.status_code, cursor.status_code), (400, 400))
        self.assertIn('antes', self.erro(cursor)['campos'])
        self.assertEqual(len(pequeno['results']), 1)
        self.assertTrue(pequeno['tem_mais_antigas'])

    def test_campos_da_mensagem(self):
        conversa = self.conversa_com_humano()

        mensagem = self.api().get(url(f'conversas/{conversa.pk}/mensagens/')).json()['results'][0]

        for campo in ('id', 'direcao', 'autor', 'autor_nome', 'tipo', 'tipo_display', 'texto', 'status',
                      'status_display', 'criado_em', 'responde_a', 'reacao_cliente', 'midia', 'pode_reenviar'):
            with self.subTest(campo=campo):
                self.assertIn(campo, mensagem)
        self.assertEqual((mensagem['direcao'], mensagem['autor_nome']), ('ENTRADA', 'Maria Souza'))


class IniciarTests(CrmApiTestCase):
    def test_iniciar_com_abertura_aprovada(self):
        modelo = self.abertura_aprovada('Boas notícias', 'Olá {nome}, temos uma novidade sobre seu pedido.')

        resposta = self.api(self.gestor).post(url('conversas/iniciar/'), {
            'telefone': '(91) 98888-1111', 'modelo': modelo.chave, 'nome': 'João Lima'}, format='json')

        conversa = Conversa.objects.get(telefone='5591988881111')
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['id'], conversa.pk)
        self.assertEqual(conversa.assumida_por, self.gestor)
        self.assertEqual(Mensagem.objects.get(conversa=conversa).origem, Mensagem.Origem.ABERTURA)

    def test_iniciar_sem_abertura_aprovada_recebe_409(self):
        resposta = self.api().post(url('conversas/iniciar/'), {'telefone': '91988881111', 'modelo': 'nao-existe'},
                                   format='json')

        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(self.erro(resposta)['codigo'], 'conflito')
        self.assertFalse(Conversa.objects.exists())

    def test_iniciar_sem_campos_recebe_400(self):
        resposta = self.api().post(url('conversas/iniciar/'), {}, format='json')

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(set(self.erro(resposta)['campos']), {'telefone', 'modelo'})
