"""Roteiro do cliente para o menu do assistente: atalhos sem IA, chave PIX, encerramento automático."""
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from crm.models import Conversa, EncaminhamentoIA, Mensagem, Nota
from crm.services import expediente
from crm.services.assistente import consulta_parcelas, identidade
from crm.tests.test_assistente import IDENTIDADE_CERTA, AssistenteBase, ferramenta, texto
from vendas.models import Loja

CHAVE_CNPJ = '60280529000138'
Assunto = EncaminhamentoIA.Assunto


class MenuBase(AssistenteBase):
    def setUp(self):
        super().setUp()
        Loja.objects.create(nome='IPIXX', credfacil=True, chave_pix=CHAVE_CNPJ)
        self.roteiro = self.com_roteiro(ferramenta('mostrar_menu', {}), texto(''))
        self.receber('oi', wamid='w-menu')
        self.chamadas_depois_do_menu = len(self.roteiro.chamadas)

    def no_horario(self, aberto: bool):
        patch = mock.patch.object(expediente, 'aberto', return_value=aberto)
        patch.start()
        self.addCleanup(patch.stop)

    def saidas_depois_do_menu(self) -> list[str]:
        saidas = Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('id')
        return [m.texto for m in saidas if not (m.dados or {}).get('menu')]

    def assert_sem_ia(self):
        self.assertEqual(len(self.roteiro.chamadas), self.chamadas_depois_do_menu)


class AtalhosTests(MenuBase):
    def test_desbloqueio_pelo_toque_na_lista_passa_direto_sem_pedir_dados(self):
        self.no_horario(True)

        self.receber('Desbloquear o aparelho', wamid='w1')

        self.assert_sem_ia()
        self.assertEqual(Conversa.objects.get().modo, Conversa.Modo.AGUARDANDO)
        self.assertEqual(EncaminhamentoIA.objects.get().assunto, Assunto.DESBLOQUEIO)
        [aviso] = self.saidas_depois_do_menu()
        self.assertIn('atendente', aviso)
        self.assertNotIn('CPF', aviso)

    def test_chave_pix_manda_cnpj_separado_link_de_consulta_e_encerra(self):
        self.receber('3', wamid='w1')

        self.assert_sem_ia()
        explicacao, chave = self.saidas_depois_do_menu()
        self.assertIn('CNPJ', explicacao)
        self.assertIn('https://credfacil.exemplo.com/consultar-pagamentos/', explicacao)
        self.assertEqual(chave, CHAVE_CNPJ)
        conversa = Conversa.objects.get()
        self.assertEqual(conversa.modo, Conversa.Modo.AUTOMATICO)
        self.assertEqual(conversa.situacao, Conversa.Situacao.RESOLVIDA)
        self.assertFalse(EncaminhamentoIA.objects.exists())
        self.assertTrue(Nota.objects.filter(conversa=conversa, texto__icontains='encerrado').exists())

    def test_depois_de_encerrar_o_historico_da_ia_comeca_do_zero(self):
        self.receber('3', wamid='w1')
        self.roteiro.passos.append(texto('Oi! Como posso ajudar?'))

        self.receber('bom dia', wamid='w2')

        conversa = Conversa.objects.get()
        self.assertEqual(conversa.situacao, Conversa.Situacao.ABERTA)
        self.assertEqual(self.roteiro.chamadas[-1], [{'role': 'user', 'content': 'bom dia'}])

    def test_parcela_em_atraso_no_horario_comercial_vai_para_a_equipe(self):
        self.no_horario(True)

        self.receber('2', wamid='w1')

        self.assert_sem_ia()
        self.assertEqual(EncaminhamentoIA.objects.get().assunto, Assunto.ATRASO)

    def test_parcela_em_atraso_fora_do_horario_segue_com_a_ia(self):
        self.no_horario(False)
        self.roteiro.passos.append(texto('Me passa seu CPF e data de nascimento, por favor.'))

        self.receber('2', wamid='w1')

        self.assertEqual(len(self.roteiro.chamadas), self.chamadas_depois_do_menu + 1)
        self.assertFalse(EncaminhamentoIA.objects.exists())

    def test_ja_quitei_novo_aparelho_avisa_e_transfere(self):
        self.no_horario(False)

        self.receber('9', wamid='w1')

        self.assert_sem_ia()
        self.assertEqual(EncaminhamentoIA.objects.get().assunto, Assunto.NOVO_APARELHO)
        [aviso] = self.saidas_depois_do_menu()
        self.assertIn('novo aparelho', aviso)
        self.assertIn('fora do nosso horário', aviso)

    def test_numero_sem_menu_recente_fica_com_a_ia(self):
        Mensagem.objects.filter(dados__menu=True).update(criado_em=timezone.now() - timedelta(hours=2))
        self.roteiro.passos.append(texto('Certo! Do que você precisa?'))

        self.receber('1', wamid='w1')

        self.assertEqual(len(self.roteiro.chamadas), self.chamadas_depois_do_menu + 1)
        self.assertFalse(EncaminhamentoIA.objects.exists())


class FerramentasDoRoteiroTests(AssistenteBase):
    def setUp(self):
        super().setUp()
        Loja.objects.create(nome='IPIXX', credfacil=True, chave_pix=CHAVE_CNPJ)

    def test_ia_manda_a_chave_pix_separada_e_encerra(self):
        self.com_roteiro(
            ferramenta('enviar_chave_pix', {}, 'tu_1'),
            ferramenta('encerrar_atendimento', {'resumo': 'Quitação informada.'}, 'tu_2'),
            texto('A chave PIX é o CNPJ e vai na próxima mensagem. Qualquer coisa, é só chamar!'),
        )

        self.receber('quero quitar', wamid='w1')

        saidas = list(Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('id')
                      .values_list('texto', flat=True))
        self.assertEqual(saidas[-1], CHAVE_CNPJ)
        conversa = Conversa.objects.get()
        self.assertEqual(conversa.situacao, Conversa.Situacao.RESOLVIDA)
        self.assertIsNotNone(identidade.encerrada_em(conversa))

    def test_nao_encerra_quando_transferiu_no_mesmo_turno(self):
        self.com_roteiro(
            ferramenta('transferir_para_atendente', {'assunto': 'NEGOCIACAO', 'motivo': 'Quer negociar.'}, 'tu_1'),
            ferramenta('encerrar_atendimento', {'resumo': 'x'}, 'tu_2'),
            texto('Vou te passar para um atendente.'),
        )

        self.receber('negociar', wamid='w1')

        conversa = Conversa.objects.get()
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertEqual(conversa.situacao, Conversa.Situacao.ABERTA)

    def test_identificacao_preserva_o_encerramento_anterior(self):
        self.com_roteiro(texto('Oi!'))
        conversa = self.receber('oi', wamid='w0').conversa
        identidade.marcar_encerramento(conversa)

        identidade.identificar(conversa, IDENTIDADE_CERTA['cpf'], IDENTIDADE_CERTA['data_nascimento'])

        self.assertIsNotNone(identidade.encerrada_em(conversa))
        self.assertTrue(identidade.clientes_verificados(conversa))

    def test_consulta_nao_descreve_o_produto_e_traz_os_totais_da_negociacao(self):
        compra = consulta_parcelas.consultar([self.cliente], timezone.localdate())['compras'][0]

        self.assertNotIn('produto', compra)
        self.assertIn('qtd_atrasadas', compra)
        self.assertIn('atrasada_mais_antiga', compra)
        self.assertEqual(compra['qtd_em_aberto'], len(compra['parcelas']))


class NomeDoClienteNoCabecalhoTests(AssistenteBase):
    def test_cabecalho_mostra_o_cliente_vinculado_so_para_quem_pode_ver(self):
        from django.contrib.auth.models import Permission

        from crm.apresentacao import conversa_estado

        conversa = Conversa.objects.create(telefone='5591988887777')
        conversa.clientes.add(self.cliente)
        usuario = self.criar_usuario('so_crm', acessar=True)  # acessa o CRM, mas não vê clientes
        self.assertEqual(conversa_estado(conversa, usuario)['clientes_nomes'], [])

        usuario.user_permissions.add(*Permission.objects.filter(codename__in=['view_cliente', 'can_view_all_stores']))
        com_permissao = self.criar_usuario_recarregado(usuario)

        self.assertEqual(conversa_estado(conversa, com_permissao)['clientes_nomes'], ['Maria Souza'])


class TextoIntermediarioTests(AssistenteBase):
    def setUp(self):
        super().setUp()
        Loja.objects.create(nome='IPIXX', credfacil=True, chave_pix=CHAVE_CNPJ)

    def test_texto_escrito_junto_com_a_ferramenta_nao_se_perde_ao_encerrar(self):
        from crm.services.assistente.ia import Chamada, RespostaIA

        com_texto = RespostaIA(
            'tool_use', ('Sua parcela de R$ 100,00 venceu em 16/11. A chave PIX (CNPJ) vai abaixo.',),
            (Chamada('tu_1', 'enviar_chave_pix', {}), Chamada('tu_2', 'encerrar_atendimento', {'resumo': 'ok'})),
            [{'type': 'text', 'text': 'x'},
             {'type': 'tool_use', 'id': 'tu_1', 'name': 'enviar_chave_pix', 'input': {}},
             {'type': 'tool_use', 'id': 'tu_2', 'name': 'encerrar_atendimento', 'input': {'resumo': 'ok'}}],
        )
        self.com_roteiro(com_texto, texto('Qualquer coisa, é só chamar!'))

        self.receber('2', wamid='w1')

        resposta, chave = Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('id')
        self.assertIn('R$ 100,00', resposta.texto)
        self.assertTrue(resposta.texto.endswith('Qualquer coisa, é só chamar!'))
        self.assertEqual(chave.texto, CHAVE_CNPJ)

    def test_link_gerado_vai_mesmo_se_o_modelo_esquecer_ao_encerrar(self):
        parcela = self.parcela_aberta()
        self.com_roteiro(
            ferramenta('identificar_cliente', IDENTIDADE_CERTA, 'tu_1'),
            ferramenta('gerar_link_pagamento', {'parcela_id': parcela.pk}, 'tu_2'),
            ferramenta('encerrar_atendimento', {'resumo': 'Atraso informado.'}, 'tu_3'),
            texto('Sua parcela de R$ 100,00 está em atraso. Até mais!'),
        )

        self.receber('52998224725 17/05/1990', wamid='w1')

        resposta = Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('id').last()
        self.assertIn('Link para pagamento: https://credfacil.exemplo.com/pagamento/', resposta.texto)
        self.assertEqual(Conversa.objects.get().situacao, Conversa.Situacao.RESOLVIDA)
