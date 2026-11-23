"""Autoatendimento de pagamentos pelo WhatsApp (CPF + nascimento) e painel do atendente."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.utils import timezone

from crm.models import ConfiguracaoCRM, Conversa, Mensagem, Nota
from crm.services import pagamentos
from crm.tests.base import CrmTestCase
from vendas.models import Cliente, ComprovantesCliente, Loja, Pagamento, Parcela, TipoPagamento, Venda

CPF_VALIDO = '52998224725'
NASCIMENTO = date(1990, 5, 17)


class PagamentosBase(CrmTestCase):
    def setUp(self):
        super().setUp()
        ConfiguracaoCRM.objects.update_or_create(pk=1, defaults={
            'autoatendimento_ativo': True, 'url_publica': 'https://credfacil.exemplo.com',
        })
        self.loja = Loja.objects.create(nome='Loja Centro')
        self.cliente = Cliente.objects.create(
            nome='Maria Souza', telefone='91999990000', cpf=CPF_VALIDO, nascimento=NASCIMENTO, rg='1',
            cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=self.loja,
            comprovantes=ComprovantesCliente.objects.create(loja=self.loja),
        )
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.atendente, loja=self.loja,
                                     repasse_logista=Decimal('100.00'))
        tipo = TipoPagamento.objects.create(nome='IPX', parcelas=True, caixa=False)
        self.pagamento = Pagamento.objects.create(venda=venda, tipo_pagamento=tipo, valor=Decimal('300.00'),
                                                  parcelas=3, loja=self.loja, data_primeira_parcela=date.today())
        hoje = date.today()
        parcelas = list(Parcela.objects.filter(pagamento=self.pagamento).order_by('numero_parcela'))
        Parcela.objects.filter(pk=parcelas[0].pk).update(pago=True, valor_pago=Decimal('100.00'),
                                                         data_vencimento=hoje - timedelta(days=40))
        Parcela.objects.filter(pk=parcelas[1].pk).update(data_vencimento=hoje - timedelta(days=10))
        Parcela.objects.filter(pk=parcelas[2].pk).update(data_vencimento=hoje + timedelta(days=20))

    def ultima_saida(self) -> Mensagem:
        return Mensagem.objects.filter(direcao=Mensagem.Direcao.SAIDA).order_by('-id').first()


class ResumoTests(PagamentosBase):
    def test_resumo_do_cliente(self):
        itens = pagamentos.resumo_do_cliente(self.cliente)

        self.assertEqual(len(itens), 1)
        item = itens[0]
        self.assertEqual((item['parcelas_abertas'], item['parcelas_atrasadas']), (2, 1))
        self.assertEqual((item['total_aberto'], item['total_atrasado']), ('200.00', '100.00'))
        self.assertEqual(item['proxima']['numero'], 3)
        self.assertEqual(item['link_publico'],
                         f'https://credfacil.exemplo.com/pagamento/{self.pagamento.token_publico}/')
        self.assertNotIn(f'/pagamento/{self.pagamento.pk}/', item['link_publico'])

    def test_pagamento_quitado_ou_desativado_fica_fora(self):
        Pagamento.objects.filter(pk=self.pagamento.pk).update(desativado=True)

        self.assertEqual(pagamentos.resumo_do_cliente(self.cliente), [])

    def test_texto_sem_parcelas_em_aberto(self):
        texto = pagamentos.texto_resumo('Maria Souza', [])

        self.assertIn('não tem parcelas em aberto', texto)


class AutoatendimentoTests(PagamentosBase):
    def test_fluxo_completo_menu_cpf_nascimento_resumo(self):
        self.receber('Oi', wamid='w1')
        conversa = Conversa.objects.get()
        menu = self.ultima_saida()
        self.receber('1', wamid='w2')
        pede_cpf = self.ultima_saida()
        self.receber('529.982.247-25', wamid='w3')
        pede_nascimento = self.ultima_saida()
        self.receber('17/05/1990', wamid='w4')
        resumo = self.ultima_saida()

        conversa.refresh_from_db()
        self.assertEqual(conversa.modo, Conversa.Modo.AUTOMATICO)
        self.assertIn('1', menu.texto)
        self.assertEqual(menu.autor, Mensagem.Autor.AUTOMATICO)
        self.assertIn('CPF', pede_cpf.texto)
        self.assertIn('nascimento', pede_nascimento.texto)
        self.assertIn('R$ 100,00', resumo.texto)
        self.assertIn(f'/pagamento/{self.pagamento.token_publico}/', resumo.texto)
        self.assertIn(self.cliente, conversa.clientes.all())

    def test_intencao_no_texto_pula_o_menu(self):
        self.receber('Quero ver minhas parcelas', wamid='w1')

        self.assertIn('CPF', self.ultima_saida().texto)

    def test_pedir_atendente_transfere(self):
        self.receber('Oi', wamid='w1')
        self.receber('2', wamid='w2')

        conversa = Conversa.objects.get()
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertTrue(Nota.objects.filter(conversa=conversa, tipo=Nota.Tipo.TRANSFERENCIA).exists())

    def test_cpf_invalido_pede_de_novo_e_nascimento_errado_tres_vezes_transfere(self):
        self.receber('1', wamid='w1')
        self.receber('123', wamid='w2')
        cpf_invalido = self.ultima_saida()
        for indice in range(3):
            self.receber(CPF_VALIDO, wamid=f'c{indice}')
            self.receber('01/01/2000', wamid=f'n{indice}')

        conversa = Conversa.objects.get()
        self.assertIn('CPF', cpf_invalido.texto)
        self.assertEqual(conversa.modo, Conversa.Modo.AGUARDANDO)
        self.assertFalse(conversa.clientes.exists())
        nota = Nota.objects.filter(conversa=conversa, tipo=Nota.Tipo.TRANSFERENCIA).latest('id')
        self.assertIn('tentativas', nota.texto)

    def test_etapa_expirada_volta_ao_menu(self):
        self.receber('1', wamid='w1')
        conversa = Conversa.objects.get()
        Conversa.objects.filter(pk=conversa.pk).update(
            contexto={'etapa': 'CPF', 'desde': (timezone.now() - timedelta(hours=2)).isoformat(), 'tentativas': 0},
        )

        self.receber(CPF_VALIDO, wamid='w2')

        self.assertIn('1', self.ultima_saida().texto)
        self.assertNotIn('nascimento', self.ultima_saida().texto)

    def test_desligado_mantem_boas_vindas_e_transferencia(self):
        ConfiguracaoCRM.objects.filter(pk=1).update(autoatendimento_ativo=False)

        self.receber('Oi', wamid='w1')

        self.assertEqual(Conversa.objects.get().modo, Conversa.Modo.AGUARDANDO)


class PainelPagamentosTests(PagamentosBase):
    def _com_permissoes(self, *codigos):
        self.loja.usuarios.add(self.atendente)
        self.atendente.user_permissions.add(*Permission.objects.filter(content_type__app_label='vendas', codename__in=codigos))
        return self.web(self.criar_usuario_recarregado(self.atendente))

    def test_painel_mostra_pagamentos_com_permissao(self):
        conversa = self.receber('Oi', wamid='w1').conversa
        conversa.clientes.add(self.cliente)
        url = f'/crm/conversas/{conversa.pk}/parte/painel/'
        sem = self._com_permissoes('view_cliente').get(url)
        com = self._com_permissoes('view_cliente', 'view_pagamento').get(url)

        self.assertEqual(sem.context['painel']['clientes'][0]['pagamentos'], [])
        self.assertNotContains(sem, 'Preparar resumo de pagamentos')
        self.assertEqual(com.context['painel']['clientes'][0]['pagamentos'][0]['parcelas_atrasadas'], 1)
        self.assertContains(com, 'Preparar resumo de pagamentos')

    def test_buscar_cliente_por_cpf_e_resumo(self):
        conversa = self.receber('Oi', wamid='w1').conversa
        web = self._com_permissoes('view_cliente', 'view_pagamento')

        achados = web.get(f'/crm/conversas/{conversa.pk}/buscar-cliente/', {'q': '529.982'})
        resumo = web.post(f'/crm/conversas/{conversa.pk}/resumo-pagamentos/', {'cliente': self.cliente.pk}).json()

        self.assertEqual([a['id'] for a in achados.context['achados']], [self.cliente.pk])
        self.assertContains(achados, '***.982.247-**')
        self.assertTrue(resumo['ok'])
        self.assertIn('R$ 100,00', resumo['texto'])

    def test_resumo_exige_ver_pagamentos(self):
        conversa = self.receber('Oi', wamid='w1').conversa
        web = self._com_permissoes('view_cliente')

        resposta = web.post(f'/crm/conversas/{conversa.pk}/resumo-pagamentos/', {'cliente': self.cliente.pk})

        self.assertEqual(resposta.status_code, 409)
        self.assertFalse(resposta.json()['ok'])
