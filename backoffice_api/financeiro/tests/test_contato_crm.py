"""Contato de cobrança ligado ao CRM no detalhe da conta: painel, linha do tempo, tentativas e notas."""
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from crm.models import Conversa, Nota, TelefoneCliente, TentativaContato
from vendas.models import Contato

from .fabricas import URL_BASE, criar_conta, parcelas_de

ANALISTA = ('ANALISTA',)
VER = ('vendas.view_pagamento',)
CRM = ('crm.acessar_crm',)
Tipo = TentativaContato.Tipo
Resultado = TentativaContato.Resultado


class ContatoCrmBase(TestCase):
    def setUp(self):
        self.loja = criar_loja()
        self.conta = criar_conta(self.loja)
        self.cliente_venda = self.conta.venda.cliente
        self.url = f'{URL_BASE}contas-a-receber/{self.conta.pk}/contato-crm/'

    def logar(self, nome: str = 'ana', permissoes: tuple = VER + CRM, lojas: tuple | None = None):
        usuario = criar_usuario(nome, permissoes=permissoes, grupos=ANALISTA,
                                lojas=(self.loja,) if lojas is None else lojas)
        return usuario, cliente_logado(usuario)

    def conversa(self, telefone: str = '5591999999999', **campos) -> Conversa:
        conversa = Conversa.objects.create(telefone=telefone, **campos)
        conversa.clientes.add(self.cliente_venda)
        return conversa


class PainelTests(ContatoCrmBase):
    def test_sem_acesso_ao_crm_mostra_so_registros_manuais(self):
        Contato.objects.create(cliente=self.cliente_venda, data=date.today(), observacao='Ligou na loja')
        TentativaContato.objects.create(cliente=self.cliente_venda, numero='91999999999', tipo=Tipo.MANUAL,
                                        resultado=Resultado.NAO_ATENDEU)
        _, cliente = self.logar(permissoes=VER)

        dados = cliente.get(self.url).json()

        self.assertFalse(dados['crm_disponivel'])
        self.assertEqual(dados['telefones'], [])
        self.assertEqual([i['origem'] for i in dados['linha_do_tempo']], ['manual'])
        self.assertEqual(dados['linha_do_tempo'][0]['texto'], 'Ligou na loja')

    def test_linha_do_tempo_junta_manual_crm_e_notas_em_ordem(self):
        agora = timezone.now()
        contato = Contato.objects.create(cliente=self.cliente_venda, data=date.today() - timedelta(days=3),
                                         observacao='Visita')
        aviso = TentativaContato.objects.create(
            cliente=self.cliente_venda, numero='91999999999', tipo=Tipo.AVISO_DIA, resultado=Resultado.ENVIADO,
            parcela=parcelas_de(self.conta)[0])
        TentativaContato.objects.filter(pk=aviso.pk).update(criado_em=agora - timedelta(days=2))
        tentativa = TentativaContato.objects.create(
            cliente=self.cliente_venda, numero='91999999999', tipo=Tipo.MANUAL, canal=TentativaContato.Canal.LIGACAO,
            resultado=Resultado.NAO_ATENDEU, observacao='Caixa postal')
        TentativaContato.objects.filter(pk=tentativa.pk).update(criado_em=agora - timedelta(days=1))
        conversa = self.conversa()
        Nota.objects.create(conversa=conversa, texto='Prometeu pagar sexta', criado_em=agora)
        Nota.objects.create(conversa=conversa, texto='Conversa assumida', automatica=True, criado_em=agora)
        Nota.objects.create(conversa=conversa, texto='Apagada', criado_em=agora, apagada_em=agora)
        _, cliente = self.logar()

        dados = cliente.get(self.url).json()

        self.assertTrue(dados['crm_disponivel'])
        self.assertTrue(dados['pode_anotar'])
        self.assertEqual(dados['conversa_id'], conversa.pk)
        linha = dados['linha_do_tempo']
        self.assertEqual([i['origem'] for i in linha], ['nota', 'tentativa', 'tentativa', 'manual'])
        self.assertEqual(linha[0]['texto'], 'Prometeu pagar sexta')
        self.assertEqual(linha[1]['resultado'], 'Não atendeu')
        self.assertEqual(linha[1]['canal'], 'Ligação')
        self.assertFalse(linha[1]['automatica'])
        self.assertTrue(linha[2]['automatica'])
        self.assertEqual(linha[2]['parcela'], 1)
        self.assertEqual(linha[3]['contato_id'], contato.pk)
        self.assertTrue(linha[3]['somente_data'])

    def test_telefones_do_cadastro_e_status(self):
        _, cliente = self.logar()

        dados = cliente.get(self.url).json()

        self.assertEqual(len(dados['telefones']), 1)
        self.assertEqual(dados['telefones'][0]['origem'], 'Principal do cadastro')
        self.assertEqual(dados['status']['codigo'], 'SEM_TENTATIVA')
        self.assertFalse(dados['pode_anotar'])
        self.assertIn('RESPONDEU', [r['valor'] for r in dados['opcoes']['resultados_cliente']])
        self.assertNotIn('REF_AJUDOU', [r['valor'] for r in dados['opcoes']['resultados_cliente']])
        self.assertIn('REF_AJUDOU', [r['valor'] for r in dados['opcoes']['resultados_referencia']])

    def test_conversa_compartilhada_com_cliente_de_outra_loja_nao_expoe_notas(self):
        compartilhada = self.conversa()
        alheio = criar_conta(criar_loja('Loja B'), cpf='98765432100')
        compartilhada.clientes.add(alheio.venda.cliente)
        Nota.objects.create(conversa=compartilhada, texto='Sobre o outro cliente', criado_em=timezone.now())
        _, cliente = self.logar(permissoes=VER + CRM + ('vendas.view_cliente',))

        dados = cliente.get(self.url).json()
        nota = cliente.post(f'{URL_BASE}contas-a-receber/{self.conta.pk}/notas/', {'texto': 'x'}, format='json')

        self.assertEqual(dados['linha_do_tempo'], [])
        self.assertIsNone(dados['conversa_id'])
        self.assertFalse(dados['pode_anotar'])
        self.assertEqual(nota.status_code, 422)

    def test_registro_manual_mostra_o_dia_ao_meio_dia_local(self):
        Contato.objects.create(cliente=self.cliente_venda, data=date(2026, 11, 20), observacao='Visita')
        _, cliente = self.logar()

        quando = cliente.get(self.url).json()['linha_do_tempo'][0]['quando']

        self.assertTrue(quando.startswith('2026-11-20T12:00:00'), quando)

    def test_serializer_de_tentativa_sem_contexto_para_o_openapi(self):
        from backoffice_api.financeiro.entradas import TentativaCrmEntradaSerializer

        self.assertIn('telefone', TentativaCrmEntradaSerializer().fields)

    def test_escopo_de_loja_e_grupo(self):
        _, outra_loja = self.logar('bia', lojas=(criar_loja('Loja B'),))
        self.assertEqual(outra_loja.get(self.url).status_code, 404)
        sem_grupo = cliente_logado(criar_usuario('caio', permissoes=VER + CRM, lojas=(self.loja,)))
        self.assertEqual(sem_grupo.get(self.url).status_code, 403)


class TentativaTests(ContatoCrmBase):
    def setUp(self):
        super().setUp()
        self.url_tentativa = f'{URL_BASE}contas-a-receber/{self.conta.pk}/tentativas/'

    def _telefone(self) -> TelefoneCliente:
        _, cliente = self.logar('sync')
        cliente.get(self.url)  # sincroniza os telefones do cadastro
        return TelefoneCliente.objects.get(cliente=self.cliente_venda)

    def test_exige_acesso_ao_crm(self):
        telefone = self._telefone()
        _, cliente = self.logar(permissoes=VER)
        resposta = cliente.post(self.url_tentativa, {'telefone': telefone.pk, 'resultado': 'NAO_ATENDEU'},
                                format='json')
        self.assertEqual(resposta.status_code, 403)

    def test_registra_e_devolve_o_painel(self):
        telefone = self._telefone()
        usuario, cliente = self.logar()

        resposta = cliente.post(self.url_tentativa, {
            'telefone': telefone.pk, 'canal': 'LIGACAO', 'resultado': 'RESPONDEU', 'observacao': 'Paga dia 10',
        }, format='json')

        self.assertEqual(resposta.status_code, 201, resposta.content)
        tentativa = TentativaContato.objects.get(cliente=self.cliente_venda)
        self.assertEqual(tentativa.usuario, usuario)
        self.assertEqual(tentativa.tipo, Tipo.MANUAL)
        self.assertEqual(resposta.json()['linha_do_tempo'][0]['texto'], 'Paga dia 10')
        self.assertEqual(resposta.json()['status']['codigo'], 'CONTATO_REALIZADO')
        telefone.refresh_from_db()
        self.assertEqual(telefone.situacao, TelefoneCliente.Situacao.VALIDO)

    def test_resultado_invalido_e_telefone_de_outro_cliente(self):
        telefone = self._telefone()
        alheio = criar_conta(self.loja, cpf='98765432100')
        telefone_alheio = TelefoneCliente.objects.create(cliente=alheio.venda.cliente, telefone='91988887777',
                                                         origem=TelefoneCliente.Origem.OUTRO)
        _, cliente = self.logar()

        invalido = cliente.post(self.url_tentativa, {'telefone': telefone.pk, 'resultado': 'REF_AJUDOU'},
                                format='json')
        self.assertEqual(invalido.status_code, 422)
        self.assertIn('referência', invalido.json()['erro']['mensagem'])
        outro = cliente.post(self.url_tentativa, {'telefone': telefone_alheio.pk, 'resultado': 'NAO_ATENDEU'},
                             format='json')
        self.assertEqual(outro.status_code, 400)
        self.assertIn('telefone', outro.json()['erro']['campos'])
        self.assertFalse(TentativaContato.objects.exists())


class NotaTests(ContatoCrmBase):
    def setUp(self):
        super().setUp()
        self.url_nota = f'{URL_BASE}contas-a-receber/{self.conta.pk}/notas/'

    def test_sem_conversa_nao_anota(self):
        _, cliente = self.logar()
        resposta = cliente.post(self.url_nota, {'texto': 'Cliente viajando'}, format='json')
        self.assertEqual(resposta.status_code, 422)
        self.assertFalse(Nota.objects.exists())

    def test_anota_na_conversa_mais_recente(self):
        agora = timezone.now()
        self.conversa('5591911110000', ultima_mensagem_em=agora - timedelta(days=5))
        recente = self.conversa('5591922220000', ultima_mensagem_em=agora)
        usuario, cliente = self.logar()

        resposta = cliente.post(self.url_nota, {'texto': 'Cliente viajando'}, format='json')

        self.assertEqual(resposta.status_code, 201, resposta.content)
        nota = Nota.objects.get()
        self.assertEqual((nota.conversa_id, nota.usuario_id), (recente.pk, usuario.pk))
        self.assertEqual(resposta.json()['linha_do_tempo'][0]['origem'], 'nota')

    def test_exige_texto_e_acesso_ao_crm(self):
        self.conversa()
        _, sem_crm = self.logar('sem', permissoes=VER)
        self.assertEqual(sem_crm.post(self.url_nota, {'texto': 'x'}, format='json').status_code, 403)
        _, cliente = self.logar()
        self.assertEqual(cliente.post(self.url_nota, {'texto': '  '}, format='json').status_code, 400)
