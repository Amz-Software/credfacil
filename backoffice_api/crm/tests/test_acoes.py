"""Posse, situação, organização, clientes, abertura, notas, lembrete e programadas."""
from datetime import timedelta

from django.utils import timezone

from crm.models import Conversa, Etiqueta, Mensagem, MensagemProgramada, Nota
from crm.tests.base import fechar_janela
from vendas.models import Loja

from .base import CrmApiTestCase, url


def _iso(delta: timedelta) -> str:
    return (timezone.now() + delta).isoformat()


class FluxoTests(CrmApiTestCase):
    def test_assumir_enviar_resolver_e_devolver(self):
        conversa = self.receber('Oi').conversa
        api = self.api()
        base = f'conversas/{conversa.pk}/'

        sem_assumir = api.post(url(f'{base}enviar/'), {'texto': 'Olá'}, format='json')
        assumida = api.post(url(f'{base}assumir/'))
        enviada = api.post(url(f'{base}enviar/'), {'texto': 'Olá, Maria!'}, format='json')
        resolvida = api.post(url(f'{base}situacao/'), {'situacao': 'RESOLVIDA', 'devolver_automatico': True},
                             format='json')

        conversa.refresh_from_db()
        self.assertEqual(sem_assumir.status_code, 409)
        self.assertEqual(self.erro(sem_assumir)['codigo'], 'conflito')
        self.assertEqual(self.erro(sem_assumir)['motivo'], 'NAO_ASSUMIDA')
        self.assertEqual(assumida.status_code, 200)
        self.assertTrue(assumida.json()['pode_responder'])
        self.assertFalse(assumida.json()['acoes']['assumir'])
        self.assertEqual(enviada.status_code, 201)
        self.assertEqual((enviada.json()['texto'], enviada.json()['status']), ('Olá, Maria!', 'ENVIADO'))
        self.assertEqual(enviada.json()['autor_nome'], self.atendente.get_full_name() or self.atendente.username)
        self.assertEqual(resolvida.status_code, 200)
        self.assertEqual((conversa.situacao, conversa.modo), ('RESOLVIDA', 'AUTOMATICO'))

    def test_devolver_conversa_de_outro_sem_gerenciar_recebe_409_e_gestor_consegue(self):
        conversa = self.conversa_com_humano(self.outro)

        recusada = self.api().post(url(f'conversas/{conversa.pk}/devolver/'))
        aceita = self.api(self.gestor).post(url(f'conversas/{conversa.pk}/devolver/'))

        conversa.refresh_from_db()
        self.assertEqual(recusada.status_code, 409)
        self.assertEqual(aceita.status_code, 200)
        self.assertEqual(conversa.modo, 'AUTOMATICO')

    def test_resolver_e_devolver_recusado_nao_muda_a_situacao(self):
        conversa = self.conversa_com_humano(self.outro)

        resposta = self.api().post(url(f'conversas/{conversa.pk}/situacao/'),
                                   {'situacao': 'RESOLVIDA', 'devolver_automatico': True}, format='json')

        conversa.refresh_from_db()
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual((conversa.situacao, conversa.modo), ('ABERTA', 'HUMANO'))

    def test_situacao_invalida_recebe_400(self):
        conversa = self.conversa_com_humano()

        resposta = self.api().post(url(f'conversas/{conversa.pk}/situacao/'), {'situacao': 'X'}, format='json')

        self.assertEqual(resposta.status_code, 400)
        self.assertIn('situacao', self.erro(resposta)['campos'])

    def test_puxar_com_auditoria_e_dono_desatualizado(self):
        conversa = self.conversa_com_humano(self.outro)
        api = self.api()

        desatualizado = api.post(url(f'conversas/{conversa.pk}/puxar/'), {'de': self.gestor.pk}, format='json')
        puxada = api.post(url(f'conversas/{conversa.pk}/puxar/'), {'de': self.outro.pk}, format='json')

        conversa.refresh_from_db()
        self.assertEqual(desatualizado.status_code, 409)
        self.assertEqual(puxada.status_code, 200)
        self.assertEqual(conversa.assumida_por, self.atendente)
        registro = self.auditorias('crm_conversa_puxada').get()
        self.assertEqual((registro.objeto_id, registro.dados['de']), (str(conversa.pk), self.outro.pk))

    def test_atribuir(self):
        conversa = self.receber('Oi').conversa

        sem_poder = self.api().post(url(f'conversas/{conversa.pk}/atribuir/'), {'usuario': self.outro.pk},
                                    format='json')
        inexistente = self.api(self.gestor).post(url(f'conversas/{conversa.pk}/atribuir/'), {'usuario': 999999},
                                                 format='json')
        sem_crm = self.api(self.gestor).post(url(f'conversas/{conversa.pk}/atribuir/'),
                                             {'usuario': self.sem_acesso.pk}, format='json')
        atribuida = self.api(self.gestor).post(url(f'conversas/{conversa.pk}/atribuir/'), {'usuario': self.outro.pk},
                                               format='json')

        conversa.refresh_from_db()
        self.assertEqual(sem_poder.status_code, 409)
        self.assertEqual(inexistente.status_code, 400)
        self.assertIn('usuario', self.erro(inexistente)['campos'])
        self.assertEqual(sem_crm.status_code, 409)
        self.assertEqual(atribuida.status_code, 200)
        self.assertEqual(conversa.assumida_por, self.outro)
        self.assertEqual(self.auditorias('crm_conversa_atribuida').get().dados['para'], self.outro.pk)


class OrganizacaoTests(CrmApiTestCase):
    def test_etiquetas_apelido_e_lembrete(self):
        conversa = self.receber('Oi').conversa
        quente = Etiqueta.objects.create(nome='Quente', cor='VERMELHO')
        inativa = Etiqueta.objects.create(nome='Velha', ativo=False)
        api = self.api()
        base = f'conversas/{conversa.pk}/'

        etiquetas = api.post(url(f'{base}etiquetas/'), {'etiquetas': [quente.pk]}, format='json')
        recusada = api.post(url(f'{base}etiquetas/'), {'etiquetas': [inativa.pk]}, format='json')
        apelido = api.post(url(f'{base}apelido/'), {'apelido': 'Dona Maria'}, format='json')
        longo = api.post(url(f'{base}apelido/'), {'apelido': 'x' * 61}, format='json')
        lembrete = api.post(url(f'{base}lembrete/'), {'lembrete_em': _iso(timedelta(days=1)), 'texto': 'Ligar'},
                            format='json')
        passado = api.post(url(f'{base}lembrete/'), {'lembrete_em': _iso(-timedelta(hours=1))}, format='json')

        self.assertEqual(etiquetas.json()['etiquetas'][0]['nome'], 'Quente')
        self.assertEqual(recusada.status_code, 409)
        self.assertEqual(apelido.json()['nome_exibicao'], 'Dona Maria')
        self.assertEqual(longo.status_code, 400)
        self.assertEqual(lembrete.json()['lembrete']['texto'], 'Ligar')
        self.assertEqual(lembrete.json()['lembrete']['para']['id'], self.atendente.pk)
        self.assertEqual(passado.status_code, 409)
        concluido = api.post(url(f'{base}lembrete/concluir/'))
        self.assertIsNone(concluido.json()['lembrete'])

    def test_notas(self):
        conversa = self.receber('Oi').conversa
        base = f'conversas/{conversa.pk}/'

        criada = self.api().post(url(f'{base}notas/'), {'texto': 'Cliente prefere à tarde'}, format='json')
        vazia = self.api().post(url(f'{base}notas/'), {'texto': ''}, format='json')
        nota_id = criada.json()['id']
        alheia = self.api(self.outro).post(url(f'{base}notas/{nota_id}/apagar/'))
        propria = self.api().post(url(f'{base}notas/{nota_id}/apagar/'))
        de_novo = self.api().post(url(f'{base}notas/{nota_id}/apagar/'))

        self.assertEqual(criada.status_code, 201)
        self.assertTrue(criada.json()['pode_apagar'])
        self.assertEqual(vazia.status_code, 400)
        self.assertEqual(alheia.status_code, 409)
        self.assertEqual(propria.status_code, 204)
        self.assertEqual(de_novo.status_code, 404)
        self.assertIsNotNone(Nota.objects.get(pk=nota_id).apagada_em)

    def test_programadas(self):
        conversa = self.conversa_com_humano()
        base = f'conversas/{conversa.pk}/'
        api = self.api()

        cedo = api.post(url(f'{base}programadas/'), {'texto': 'Lembrete', 'enviar_em': _iso(timedelta())},
                        format='json')
        criada = api.post(url(f'{base}programadas/'), {'texto': 'Lembrete', 'enviar_em': _iso(timedelta(hours=2))},
                          format='json')
        programada_id = criada.json()['id']
        detalhe = api.get(url(base)).json()
        cancelada = api.post(url(f'programadas/{programada_id}/cancelar/'))
        de_novo = api.post(url(f'programadas/{programada_id}/cancelar/'))

        self.assertEqual(cedo.status_code, 409)
        self.assertEqual((criada.status_code, criada.json()['status']), (201, 'AGENDADA'))
        self.assertTrue(detalhe['tem_programada'])
        self.assertEqual([p['id'] for p in detalhe['programadas']], [programada_id])
        self.assertEqual(cancelada.json()['status'], 'CANCELADA')
        self.assertEqual(de_novo.status_code, 409)
        self.assertEqual(MensagemProgramada.objects.get().status, 'CANCELADA')


class ClientesTests(CrmApiTestCase):
    def setUp(self):
        super().setUp()
        self.loja = Loja.objects.create(nome='Minha')
        self.loja.usuarios.add(self.atendente)
        self.atendente = self.dar_permissao(self.atendente, 'vendas.view_cliente', 'vendas.view_pagamento')

    def test_sugere_busca_vincula_e_desvincula(self):
        cliente = self.criar_cliente(self.loja)
        conversa = self.receber('Oi', telefone='559199990000').conversa
        api = self.api()

        sugeridos = api.get(url(f'conversas/{conversa.pk}/')).json()['painel']['sugeridos']
        busca = api.get(url('clientes/'), {'busca': 'Maria', 'conversa': conversa.pk}).json()
        curta = api.get(url('clientes/'), {'busca': 'Ma'}).json()
        painel = api.post(url(f'conversas/{conversa.pk}/vincular-cliente/'), {'cliente': cliente.pk},
                          format='json').json()
        busca_depois = api.get(url('clientes/'), {'busca': 'Maria', 'conversa': conversa.pk}).json()
        resumo = api.get(url(f'conversas/{conversa.pk}/resumo-pagamentos/'), {'cliente': cliente.pk})
        desvinculado = api.post(url(f'conversas/{conversa.pk}/desvincular-cliente/'), {'cliente': cliente.pk},
                                format='json').json()

        self.assertEqual([s['id'] for s in sugeridos], [cliente.pk])
        self.assertEqual(busca['results'][0]['cpf'], '***.456.789-**')
        self.assertTrue(curta['busca_curta'])
        self.assertEqual(painel['clientes'][0]['cpf'], '***.456.789-**')
        self.assertEqual(painel['clientes'][0]['vendas'], [])  # sem vendas.view_venda
        self.assertEqual(busca_depois['results'], [])
        self.assertEqual(resumo.status_code, 200)
        self.assertIn('não tem parcelas em aberto', resumo.json()['texto'])
        self.assertEqual(desvinculado['clientes'], [])
        self.assertEqual(self.auditorias('crm_cliente_vinculado').count(), 1)
        self.assertEqual(self.auditorias('crm_cliente_desvinculado').count(), 1)

    def test_cliente_de_outra_loja(self):
        alheio = self.criar_cliente(Loja.objects.create(nome='Outra'))
        conversa = self.receber('Oi', telefone='559199990000').conversa
        api = self.api()

        vincular = api.post(url(f'conversas/{conversa.pk}/vincular-cliente/'), {'cliente': alheio.pk}, format='json')
        busca = api.get(url('clientes/'), {'busca': 'Maria'}).json()
        conversa.clientes.add(alheio)  # vinculado por alguém de outra loja
        painel = api.get(url(f'conversas/{conversa.pk}/')).json()['painel']
        resumo = api.get(url(f'conversas/{conversa.pk}/resumo-pagamentos/'), {'cliente': alheio.pk})

        self.assertEqual(vincular.status_code, 409)
        self.assertEqual(busca['results'], [])
        self.assertEqual(painel['clientes'], [])
        self.assertEqual(resumo.status_code, 409)


class AberturaTests(CrmApiTestCase):
    def test_janela_fechada_bloqueia_texto_e_libera_abertura(self):
        conversa = self.conversa_com_humano()
        fechar_janela(conversa)
        modelo = self.abertura_aprovada('Retomar contato', 'Olá {nome}, podemos continuar seu atendimento?')
        api = self.api()

        estado = api.get(url(f'conversas/{conversa.pk}/')).json()
        texto = api.post(url(f'conversas/{conversa.pk}/enviar/'), {'texto': 'Oi'}, format='json')
        abertura = api.post(url(f'conversas/{conversa.pk}/abrir/'), {'modelo': modelo.chave}, format='json')
        repetida = api.post(url(f'conversas/{conversa.pk}/abrir/'), {'modelo': modelo.chave}, format='json')

        conversa.refresh_from_db()
        self.assertTrue(estado['acoes']['enviar_abertura'])
        self.assertFalse(estado['janela']['aberta'])
        self.assertEqual(self.erro(texto)['motivo'], 'JANELA_FECHADA')
        self.assertEqual(abertura.status_code, 200)
        enviada = Mensagem.objects.get(origem=Mensagem.Origem.ABERTURA)
        self.assertEqual(enviada.texto, 'Olá Maria, podemos continuar seu atendimento?')
        self.assertEqual(conversa.situacao, Conversa.Situacao.PENDENTE)
        self.assertEqual(repetida.status_code, 409)  # antispam de 24 h
