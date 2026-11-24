"""Testes unitários das regras em vendas/services (uma implementação para web e API)."""
import json
from unittest import mock
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from notifications.models import Notification

from accounts.models import User
from estoque.models import EstoqueImei
from financeiro.models import Repasse
from produtos.models import Marca, Parcelamento, Produto
from vendas.models import (
    AnaliseCreditoCliente, Cliente, ComprovantesCliente, Loja, Pagamento, Parcela,
    ProdutoVenda, TipoPagamento, Venda,
)
from vendas.services import ErroDeNegocio
from vendas.services import analise as servico_analise
from vendas.services.kpis import analises_visiveis, contar_por_status, resumo_carteira_loja
from vendas.services.lojas import (
    periodos_de_repasse, replicar_qr_code_aplicativo, status_repasses_por_loja,
)
from vendas.services.notificacoes import notificar_grupos
from vendas.services.parcelas import calcular_data_primeira_parcela, criar_parcelas
from vendas.services.venda import gerar_venda_da_analise, validar_analise_para_venda


def criar_usuario(username, loja, *grupos):
    user = User.objects.create_user(username=username, email=f'{username}@t.com', password='x', loja=loja)
    for grupo in grupos:
        user.groups.add(Group.objects.get_or_create(name=grupo)[0])
    return user


def criar_cliente(loja, nome='Maria', cpf='11122233344'):
    return Cliente.objects.create(
        nome=nome, telefone='91999999999', cpf=cpf, nascimento=date(1990, 1, 1), rg='1',
        cep='66000000', endereco='Rua A', bairro='Centro', cidade='Belém', loja=loja,
        comprovantes=ComprovantesCliente.objects.create(),
    )


class CenarioMixin:
    """Loja, marca com parcelamento 10x (20% juros), produto Android e análise aprovada."""

    def montar_cenario(self, *, is_iphone=False):
        self.loja = Loja.objects.create(nome='loja centro')
        self.vendedor = criar_usuario('vendedor', self.loja, 'VENDEDOR')
        self.analista = criar_usuario('analista', self.loja, 'ANALISTA')
        self.marca = Marca.objects.create(nome='Samsung')
        Parcelamento.objects.create(
            marca=self.marca, qtd_vezes=10,
            porcentagem_juros=Decimal('20'), porcentagem_desconto=Decimal('5'),
        )
        self.produto = Produto.objects.create(
            nome='Galaxy', valor=Decimal('1200.00'), entrada_cliente=Decimal('200.00'),
            marca=self.marca, is_iphone=is_iphone,
        )
        TipoPagamento.objects.get_or_create(nome='ENTRADA', defaults={'caixa': True})
        TipoPagamento.objects.get_or_create(nome='IPX', defaults={'parcelas': True})
        self.cliente = criar_cliente(self.loja)
        self.imei = EstoqueImei.objects.create(produto=self.produto, imei='350000000000001', loja=self.loja)
        self.analise = AnaliseCreditoCliente.objects.create(
            cliente=self.cliente, produto=self.produto, loja=self.loja, status='A',
            status_aplicativo='I', imei=self.imei, data_pagamento='10', numero_parcelas='10',
        )


class CalcularDataPrimeiraParcelaTests(TestCase):
    def test_escolhe_a_data_mais_distante_dentro_de_30_dias(self):
        self.assertEqual(calcular_data_primeira_parcela('10', hoje=date(2026, 3, 15)), date(2026, 4, 10))
        self.assertEqual(calcular_data_primeira_parcela('10', hoje=date(2026, 3, 5)), date(2026, 3, 10))

    def test_mesmo_mes_quando_o_proximo_passa_de_30_dias(self):
        self.assertEqual(calcular_data_primeira_parcela('20', hoje=date(2026, 3, 1)), date(2026, 3, 20))

    def test_vira_o_ano(self):
        self.assertEqual(calcular_data_primeira_parcela('1', hoje=date(2026, 12, 15)), date(2027, 1, 1))

    def test_nunca_no_proprio_dia(self):
        self.assertEqual(calcular_data_primeira_parcela('10', hoje=date(2026, 4, 10)), date(2026, 5, 10))

    def test_sem_data_na_janela_devolve_none(self):
        # 10/03 → 10/04 são 31 dias: nenhuma data com dia 10 cabe em 30 dias.
        self.assertIsNone(calcular_data_primeira_parcela('10', hoje=date(2026, 3, 10)))


class CriarParcelasTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=self.loja,
                                     repasse_logista=Decimal('0'))
        self.pagamento = Pagamento.objects.create(
            venda=venda, tipo_pagamento=TipoPagamento.objects.get(nome='IPX'), valor=Decimal('300.00'),
            parcelas=3, loja=self.loja, data_primeira_parcela=date(2026, 12, 31),
        )

    def test_mantem_o_dia_e_ajusta_meses_curtos(self):
        criar_parcelas(self.pagamento, self.loja)

        parcelas = list(self.pagamento.parcelas_pagamento.order_by('numero_parcela'))
        self.assertEqual([p.data_vencimento for p in parcelas],
                         [date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28)])
        self.assertTrue(all(p.valor == Decimal('100.00') and p.loja == self.loja for p in parcelas))

    def test_recria_sem_duplicar(self):
        criar_parcelas(self.pagamento, self.loja)
        criar_parcelas(self.pagamento, self.loja)
        self.assertEqual(self.pagamento.parcelas_pagamento.count(), 3)


class GerarVendaDaAnaliseTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def gerar(self, **kwargs):
        kwargs.setdefault('bloquear_imei_de_venda_cancelada', True)
        return gerar_venda_da_analise(self.cliente, self.vendedor, **kwargs)

    def test_cria_venda_produto_e_pagamentos_com_juros_do_parcelamento(self):
        venda = self.gerar()

        self.assertEqual(venda.repasse_logista, Decimal('1000.00'))
        item = venda.itens_venda.get()
        self.assertEqual((item.imei, item.valor_unitario), (self.imei.imei, Decimal('1200.00')))
        entrada = venda.pagamentos.get(tipo_pagamento__nome='ENTRADA')
        ipx = venda.pagamentos.get(tipo_pagamento__nome='IPX')
        self.assertEqual((entrada.valor, entrada.parcelas), (Decimal('200.00'), 1))
        self.assertEqual((ipx.valor, ipx.parcelas, ipx.porcentagem_desconto),
                         (Decimal('1200.00'), 10, Decimal('5.00')))
        self.assertEqual(ipx.parcelas_pagamento.count(), 10)
        self.assertEqual(ipx.data_primeira_parcela.day, 10)
        self.analise.refresh_from_db()
        self.assertEqual(self.analise.venda, venda)

    def test_entrada_informada_maior_reduz_o_financiado(self):
        self.analise.entrada_informada = Decimal('400.00')
        self.analise.save()

        venda = self.gerar()

        self.assertEqual(venda.pagamentos.get(tipo_pagamento__nome='IPX').valor, Decimal('960.00'))

    def test_comodato_nao_tem_repasse_ao_lojista(self):
        self.analise.comodato = True
        self.analise.save()

        venda = self.gerar()

        self.assertTrue(venda.comodato)
        self.assertEqual(venda.repasse_logista, Decimal('0'))
        # O cliente paga igual: só muda o destino do dinheiro.
        self.assertEqual(venda.pagamentos.get(tipo_pagamento__nome='IPX').valor, Decimal('1200.00'))

    def test_juros_do_comodato_iguais_aos_da_venda_comum(self):
        comum = self.gerar()
        self.assertEqual(comum.juros, Decimal('200.00'))

        venda = Venda.objects.get(pk=comum.pk)
        Venda.objects.filter(pk=venda.pk).update(comodato=True, repasse_logista=0)
        comodato = Venda.objects.get(pk=venda.pk)
        self.assertEqual(comodato.juros, Decimal('200.00'))

    def test_repasse_da_loja_ignora_vendas_de_comodato(self):
        venda = self.gerar()
        self.assertEqual(self.loja.calcular_valor_repasse(None, None), Decimal('1000.00'))

        Venda.objects.filter(pk=venda.pk).update(comodato=True, repasse_logista=0)

        self.assertEqual(self.loja.calcular_valor_repasse(None, None), 0)

    def assert_erro(self, trecho, *, na_edicao=None, **kwargs):
        with self.assertRaises(ErroDeNegocio) as ctx:
            self.gerar(**kwargs)
        self.assertIn(trecho, ctx.exception.mensagem)
        if na_edicao is not None:
            self.assertEqual(ctx.exception.corrigir_na_edicao, na_edicao)
        self.assertFalse(Venda.objects.exists())

    def test_exige_analise_aprovada(self):
        self.analise.status = 'EA'
        self.analise.save()
        self.assert_erro('não aprovada', na_edicao=False)

    def test_exige_app_instalado_em_android(self):
        self.analise.status_aplicativo = 'C'
        self.analise.save()
        self.assert_erro('Aplicativo não está instalado', na_edicao=True)

    def test_iphone_dispensa_app_instalado(self):
        self.produto.is_iphone = True
        self.produto.save()
        self.analise.status_aplicativo = 'P'
        self.analise.save()
        self.assertIsNotNone(self.gerar())

    def test_entrada_abaixo_do_minimo(self):
        self.analise.entrada_informada = Decimal('100.00')
        self.analise.save()
        self.assert_erro('entrada mínima', na_edicao=True)

    def test_sem_parcelamento_para_a_quantidade(self):
        self.analise.numero_parcelas = '7'
        self.analise.save()
        self.assert_erro("Nenhum parcelamento cadastrado para 7x na marca 'Samsung'")

    def test_sem_data_de_pagamento(self):
        self.analise.data_pagamento = None
        self.analise.save()
        self.assert_erro('Data de pagamento não informada')

    def test_sem_vencimento_possivel_avisa_em_vez_de_quebrar(self):
        with mock.patch('vendas.services.venda.calcular_data_primeira_parcela', return_value=None):
            self.assert_erro('dia de pagamento', na_edicao=True)

    def test_imei_em_venda_cancelada_bloqueia_so_no_backoffice(self):
        outra = Venda.objects.create(cliente=criar_cliente(self.loja, 'Outro', '999'), vendedor=self.vendedor,
                                     loja=self.loja, repasse_logista=0, is_deleted=True)
        ProdutoVenda.objects.create(venda=outra, produto=self.produto, imei=self.imei.imei,
                                    valor_unitario=1, quantidade=1, loja=self.loja)

        with self.assertRaises(ErroDeNegocio):
            self.gerar(bloquear_imei_de_venda_cancelada=True)
        self.assertIsNotNone(self.gerar(bloquear_imei_de_venda_cancelada=False))

    def test_cpf_com_venda_anterior_sem_3_parcelas_pagas(self):
        anterior = Venda.objects.create(cliente=criar_cliente(self.loja, 'Maria 2'), vendedor=self.vendedor,
                                        loja=self.loja, repasse_logista=0)
        self.assertEqual(anterior.cliente.cpf, self.cliente.cpf)
        with self.assertRaises(ErroDeNegocio) as ctx:
            self.gerar()
        self.assertIn('3 parcelas pagas', ctx.exception.mensagem)

    def test_venda_ja_gerada(self):
        self.analise.venda = Venda.objects.create(
            cliente=criar_cliente(self.loja, 'Outro', '999'), vendedor=self.vendedor,
            loja=self.loja, repasse_logista=0,
        )
        with self.assertRaises(ErroDeNegocio) as ctx:
            validar_analise_para_venda(self.analise, bloquear_imei_de_venda_cancelada=True)
        self.assertIn('já foi convertida em venda', ctx.exception.mensagem)


class TransicoesDaAnaliseTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()
        self.analise.status = 'EA'
        self.analise.status_aplicativo = 'P'
        self.analise.imei = None
        self.analise.save()

    def test_aprovar_registra_quem_aprovou(self):
        servico_analise.aprovar_analise(self.analise, self.analista)
        self.analise.refresh_from_db()
        self.assertEqual((self.analise.status, self.analise.aprovado_por), ('A', self.analista))
        self.assertEqual(self.analise.modificado_por, self.analista)

    def test_reprovar(self):
        servico_analise.reprovar_analise(self.analise, self.analista)
        self.analise.refresh_from_db()
        self.assertEqual(self.analise.status, 'R')
        self.assertIsNotNone(self.analise.data_reprovacao)

    def test_cancelar_sem_desfazer_mantem_a_venda(self):
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=self.loja, repasse_logista=0)
        self.analise.venda = venda
        self.analise.save()

        servico_analise.cancelar_analise(self.analise, self.analista)

        venda.refresh_from_db()
        self.assertEqual(self.analise.status, 'C')
        self.assertFalse(venda.is_deleted)

    def test_cancelar_desfazendo_cancela_venda_e_libera_imei(self):
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=self.loja, repasse_logista=0)
        self.imei.vendido = True
        self.imei.save()
        self.analise.venda, self.analise.imei = venda, self.imei
        self.analise.save()

        servico_analise.cancelar_analise(self.analise, self.analista, desfazer_venda=True)

        venda.refresh_from_db()
        self.imei.refresh_from_db()
        self.assertTrue(venda.is_deleted)
        self.assertFalse(self.imei.vendido)

    def test_status_do_app_invalido(self):
        with self.assertRaises(ErroDeNegocio):
            servico_analise.atualizar_status_aplicativo(self.analise, 'X')

    def test_vendedor_confirma_instalacao_e_avisa_analistas(self):
        servico_analise.confirmar_instalacao_vendedor(self.analise, self.vendedor, digitos='1234')

        self.analise.refresh_from_db()
        self.assertEqual((self.analise.status_aplicativo, self.analise.imei_ultimos_digitos_vendedor), ('C', '1234'))
        aviso = Notification.objects.filter(recipient=self.analista, verb__startswith='Vendedor confirmou instalação').get()
        self.assertIn('IMEI termina em 1234', aviso.description)

    def test_analista_informa_imei_novo_e_libera_android(self):
        servico_analise.marcar_instalacao_pendente(self.analise)

        analise, criado = servico_analise.informar_imei(self.analise, self.analista, ' 350000000000099 ', self.loja)

        self.assertTrue(criado)
        self.assertEqual((analise.imei.imei, analise.imei_informado, analise.status_aplicativo),
                         ('350000000000099', '350000000000099', 'I'))
        self.assertEqual(analise.imei.criado_por, self.analista)

    def test_informar_imei_reaproveita_o_do_estoque(self):
        servico_analise.marcar_instalacao_pendente(self.analise)
        _, criado = servico_analise.informar_imei(self.analise, self.analista, self.imei.imei, self.loja)
        self.assertFalse(criado)
        self.assertEqual(self.analise.imei, self.imei)

    def test_informar_imei_exige_analista_e_instalacao(self):
        with self.assertRaises(ErroDeNegocio) as ctx:
            servico_analise.informar_imei(self.analise, self.vendedor, '1', self.loja)
        self.assertEqual(ctx.exception.status_http, 403)
        with self.assertRaises(ErroDeNegocio) as ctx:
            servico_analise.informar_imei(self.analise, self.analista, '1', self.loja)
        self.assertIn('instalação do aplicativo', ctx.exception.mensagem)

    def test_informar_imei_vazio_vai_para_edicao(self):
        servico_analise.marcar_instalacao_pendente(self.analise)
        with self.assertRaises(ErroDeNegocio) as ctx:
            servico_analise.informar_imei(self.analise, self.analista, '', self.loja)
        self.assertTrue(ctx.exception.corrigir_na_edicao)

    def test_analista_confirma_instalacao(self):
        with self.assertRaises(ErroDeNegocio):
            servico_analise.confirmar_instalacao_analista(self.analise, self.analista)
        self.analise.imei = self.imei
        self.analise.status_aplicativo = 'C'
        self.analise.save()

        servico_analise.confirmar_instalacao_analista(self.analise, self.analista)

        self.assertEqual(self.analise.status_aplicativo, 'I')

    def test_fluxo_icloud(self):
        with self.assertRaises(ErroDeNegocio):
            servico_analise.configurar_icloud(self.analise, self.vendedor, '12a')
        with self.assertRaises(ErroDeNegocio):
            servico_analise.confirmar_icloud_analista(self.analise, self.analista)

        servico_analise.configurar_icloud(self.analise, self.vendedor, '99-12-34')
        servico_analise.confirmar_icloud_analista(self.analise, self.analista)

        self.analise.refresh_from_db()
        self.assertEqual(self.analise.imei_ultimos_digitos_vendedor, '9912')
        self.assertTrue(self.analise.icloud_configurado_vendedor and self.analise.icloud_confirmado_analista)
        self.assertTrue(Notification.objects.filter(
            recipient=self.vendedor, verb__startswith='Analista confirmou configuração iCloud').exists())


class NotificarGruposTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def test_um_aviso_por_usuario_e_nunca_para_o_autor(self):
        self.analista.groups.add(Group.objects.get_or_create(name='ADMINISTRADOR')[0])
        Notification.objects.all().delete()

        total = notificar_grupos(grupos=('ADMINISTRADOR', 'ANALISTA', 'VENDEDOR'), autor=self.vendedor,
                                 instance=self.analise, target=self.cliente, verb='v', description='d')

        self.assertEqual(total, 1)
        self.assertEqual(Notification.objects.filter(recipient=self.analista).count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.vendedor).exists())


class KpisTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def test_contagem_por_status_preenche_zeros(self):
        self.assertEqual(contar_por_status(AnaliseCreditoCliente.objects.all()), {'EA': 0, 'A': 1, 'R': 0, 'C': 0})

    def test_analises_visiveis_respeita_a_loja(self):
        outra = Loja.objects.create(nome='outra')
        self.assertEqual(analises_visiveis(self.vendedor, outra.id).count(), 0)
        self.assertEqual(analises_visiveis(self.vendedor, self.loja.id).count(), 1)

    def test_resumo_da_carteira_usa_as_3_primeiras_parcelas_ipx(self):
        gerar_venda_da_analise(self.cliente, self.vendedor, bloquear_imei_de_venda_cancelada=True)
        ipx = Pagamento.objects.get(tipo_pagamento__nome='IPX')
        parcelas = list(ipx.parcelas_pagamento.order_by('data_vencimento'))
        parcelas[0].pago = True
        parcelas[0].valor_pago = Decimal('150.00')
        parcelas[0].save()
        hoje = parcelas[1].data_vencimento + timedelta(days=1)

        with self.assertNumQueries(4):
            resumo = resumo_carteira_loja(self.loja, hoje=hoje)

        self.assertEqual(resumo['total_vendas_loja'], 1)
        self.assertEqual((resumo['parcelas_pagas'], resumo['parcelas_vencidas'], resumo['parcelas_a_vencer']), (1, 1, 1))
        self.assertEqual(resumo['total_de_parcelas_geral'], 3)
        self.assertEqual(resumo['total_pagas'], Decimal('150.00'))
        self.assertEqual(resumo['total_vencidas'], Decimal('120.00'))
        self.assertEqual(resumo['total_geral_parcelas'], Decimal('390.00'))
        self.assertEqual(json.loads(resumo['dash'])['labels'], ['Pagas', 'Vencidas', 'Desativados'])

    def test_desativados_ficam_fora_das_ativas(self):
        gerar_venda_da_analise(self.cliente, self.vendedor, bloquear_imei_de_venda_cancelada=True)
        Pagamento.objects.filter(tipo_pagamento__nome='IPX').update(desativado=True)

        resumo = resumo_carteira_loja(self.loja, hoje=date(2000, 1, 1))

        self.assertEqual(resumo['total_de_parcelas_geral'], 0)
        self.assertEqual((resumo['qtd_desativados_a_vencer'], resumo['total_pagamentos_desativados']), (10, 1))


class LojasTests(CenarioMixin, TestCase):
    def setUp(self):
        self.montar_cenario()

    def test_replicar_qr_code_exige_origem_configurada(self):
        with self.assertRaises(ErroDeNegocio):
            replicar_qr_code_aplicativo(self.loja)

        self.loja.qr_code_aplicativo = 'qr_codes_aplicativo/app.png'
        self.loja.codigo_aplicativo = 'ABC'
        self.loja.save()
        outra = Loja.objects.create(nome='outra')

        self.assertEqual(replicar_qr_code_aplicativo(self.loja), 1)
        outra.refresh_from_db()
        self.assertEqual((outra.codigo_aplicativo, outra.qr_code_aplicativo.name), ('ABC', 'qr_codes_aplicativo/app.png'))

    def test_periodos_do_mes_seguem_o_calendario(self):
        periodos = periodos_de_repasse(date(2026, 1, 20))
        self.assertEqual([(p.data, p.inicio, p.fim) for p in periodos], [
            (date(2026, 1, 6), date(2025, 12, 26), date(2026, 1, 5)),
            (date(2026, 1, 16), date(2026, 1, 6), date(2026, 1, 15)),
            (date(2026, 1, 26), date(2026, 1, 16), date(2026, 1, 25)),
        ])
        self.assertEqual(len(periodos_de_repasse(date(2026, 1, 20), meses_atras=20)), 21)

    def _venda_em(self, loja, dia, valor):
        venda = Venda.objects.create(cliente=self.cliente, vendedor=self.vendedor, loja=loja, repasse_logista=valor)
        momento = timezone.make_aware(datetime.combine(dia, time(12)))
        Venda.objects.filter(pk=venda.pk).update(data_venda=momento)

    def test_status_em_lote_com_consultas_fixas_e_repasse_parcial(self):
        hoje = date.today()
        lojas = [self.loja] + [Loja.objects.create(nome=f'l{i}') for i in range(3)]
        periodo_atual = periodos_de_repasse(hoje)[0]
        for loja in lojas:
            self._venda_em(loja, periodo_atual.inicio, Decimal('100.00'))
            self._venda_em(loja, periodo_atual.fim, Decimal('50.00'))
        repasse = Repasse.objects.create(
            loja=self.loja, valor=Decimal('10.00'), status='pendente', criado_por=self.vendedor,
            atualizado_por=self.vendedor,
            data=timezone.make_aware(datetime.combine(periodo_atual.data, time(12))),
        )

        with self.assertNumQueries(3):  # vendas + repasses + save do parcial
            status = status_repasses_por_loja(lojas, hoje=hoje)

        resultados, _ = status[self.loja.id]
        self.assertEqual(resultados[0]['qtd_vendas'], 2)
        self.assertEqual(resultados[0]['valor_total_repasse'], Decimal('150.00'))
        self.assertTrue(resultados[0]['feito'])
        self.assertFalse(status[lojas[1].id][0][0]['feito'])
        repasse.refresh_from_db()
        self.assertEqual(repasse.status, 'parcial')

    def test_get_repasses_status_do_modelo_usa_a_mesma_regra(self):
        hoje = date.today()
        self._venda_em(self.loja, periodos_de_repasse(hoje)[0].inicio, Decimal('70.00'))
        self.assertEqual(self.loja.get_repasses_status(), status_repasses_por_loja([self.loja])[self.loja.id])
