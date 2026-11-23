"""Lojas: lista, detalhe (KPIs, calendário, vendas), criação, edição, arquivos e QR code."""
import shutil
import tempfile
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from django.test import TestCase, override_settings

from backoffice_api.tests.fabricas import cliente_logado, criar_loja, criar_usuario
from financeiro.models import Repasse
from vendas.models import Loja

from .fabricas import URL_BASE, criar_repasse, criar_venda, ids, imagem_png, ultima_auditoria

VER = ('vendas.view_loja',)
MEDIA_TESTE = tempfile.mkdtemp(prefix='bo_lojas_')


def dia_do_mes_anterior(dia: int) -> date:
    return (date.today().replace(day=1) - relativedelta(months=1)).replace(day=dia)


class ListaLojasTests(TestCase):
    def setUp(self):
        self.loja_a = criar_loja('Alfa')
        self.loja_b = criar_loja('Beta')

    def test_sem_permissao_403_e_escopo(self):
        self.assertEqual(cliente_logado(criar_usuario('sem', lojas=(self.loja_a,))).get(URL_BASE).status_code, 403)
        comum = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja_a,)))
        self.assertEqual(ids(comum.get(URL_BASE)), [self.loja_a.pk])
        self.assertEqual(comum.get(URL_BASE, HTTP_X_LOJA=str(self.loja_b.pk)).status_code, 403)
        gerente = cliente_logado(criar_usuario('ger', permissoes=VER, gerente_de=(self.loja_b,)))
        self.assertEqual(ids(gerente.get(URL_BASE)), [self.loja_b.pk])
        admin = cliente_logado(criar_usuario('adm', permissoes=VER + ('vendas.can_view_all_stores',)))
        self.assertEqual(ids(admin.get(URL_BASE, HTTP_X_LOJA='todas')), [self.loja_a.pk, self.loja_b.pk])

    def test_busca_filtro_de_repasse_e_situacao(self):
        admin_user = criar_usuario('adm', permissoes=VER + ('vendas.can_view_all_stores',))
        admin = cliente_logado(admin_user)
        self.assertEqual(ids(admin.get(URL_BASE, {'busca': 'bet'})), [self.loja_b.pk])
        criar_repasse(self.loja_a, date.today() - timedelta(days=3), admin_user)
        self.assertEqual(ids(admin.get(URL_BASE, {'repasse': 'pendente'})), [self.loja_a.pk])
        self.assertEqual(ids(admin.get(URL_BASE, {'repasse': 'sem_pendente'})), [self.loja_b.pk])
        self.assertEqual(admin.get(URL_BASE, {'repasse': 'xpto'}).status_code, 400)
        linha = admin.get(URL_BASE, {'busca': 'beta'}).json()['results'][0]
        self.assertEqual(linha['repasses'], {'situacao': 'sem_dados', 'atrasados': 0})
        self.assertNotIn('porcentagem_desconto_4', linha)


class DetalheLojaTests(TestCase):
    def setUp(self):
        self.loja = criar_loja('Alfa')
        self.outra = criar_loja('Beta')
        self.venda = criar_venda(self.loja, dia_do_mes_anterior(10), repasse='700.00')

    def test_detalhe_com_kpis_e_calendario_sem_mutacao(self):
        user = criar_usuario('fin', permissoes=VER + ('financeiro.view_repasse',), lojas=(self.loja,))
        repasse = criar_repasse(self.loja, dia_do_mes_anterior(16), user, valor='100.00')
        resposta = cliente_logado(user).get(f'{URL_BASE}{self.loja.pk}/')
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados['kpis']['qtd_vendas'], 1)
        self.assertEqual(dados['kpis']['valor_repasse'], '700.00')
        periodo = next(p for p in dados['calendario_repasses']['periodos']
                       if p['data'] == dia_do_mes_anterior(16).isoformat())
        self.assertTrue(periodo['feito'])
        self.assertTrue(periodo['parcial'])
        self.assertEqual(periodo['valor_total_repasse'], '700.00')
        repasse.refresh_from_db()
        self.assertEqual(repasse.status, 'pendente')  # GET não grava 'parcial'
        self.assertNotIn('porcentagem_desconto_4', dados['loja'])

    def test_calendario_so_com_view_repasse_e_escopo(self):
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja,)))
        self.assertIsNone(cliente.get(f'{URL_BASE}{self.loja.pk}/').json()['calendario_repasses'])
        self.assertEqual(cliente.get(f'{URL_BASE}{self.outra.pk}/').status_code, 404)
        self.assertEqual(cliente.get(f'{URL_BASE}{self.loja.pk}/', {'data_inicio': 'ontem'}).status_code, 400)

    def test_vendas_do_periodo_paginadas(self):
        criar_venda(self.loja, date.today())
        cliente = cliente_logado(criar_usuario('comum', permissoes=VER, lojas=(self.loja,)))
        resposta = cliente.get(f'{URL_BASE}{self.loja.pk}/vendas/', {'page_size': 1})
        self.assertEqual(resposta.json()['count'], 2)
        self.assertEqual(len(resposta.json()['results']), 1)
        filtrada = cliente.get(f'{URL_BASE}{self.loja.pk}/vendas/', {'data_inicio': date.today().isoformat()})
        self.assertEqual(filtrada.json()['count'], 1)


@override_settings(MEDIA_ROOT=MEDIA_TESTE)
class EscritaLojaTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TESTE, ignore_errors=True)

    def setUp(self):
        self.loja = criar_loja('Alfa')

    def test_criar_exige_permissao_e_audita(self):
        sem = cliente_logado(criar_usuario('sem', permissoes=VER))
        self.assertEqual(sem.post(URL_BASE, {'nome': 'Nova'}, format='json').status_code, 403)
        cliente = cliente_logado(criar_usuario('cad', permissoes=('vendas.add_loja',)))
        contrato = {'time': 1, 'blocks': [{'type': 'paragraph', 'data': {'text': 'Cláusula'}}], 'version': '2'}
        resposta = cliente.post(URL_BASE, {'nome': 'Nova', 'telefone': '91999', 'contrato': contrato}, format='json')
        self.assertEqual(resposta.status_code, 201, resposta.content)
        loja = Loja.objects.get(pk=resposta.json()['id'])
        self.assertEqual(loja.contrato['blocks'][0]['type'], 'paragraph')
        self.assertIsNotNone(ultima_auditoria('loja_criada'))

    def test_validacoes(self):
        cliente = cliente_logado(criar_usuario('cad', permissoes=('vendas.add_loja',)))
        self.assertIn('nome', cliente.post(URL_BASE, {}, format='json').json()['erro']['campos'])
        legado = cliente.post(URL_BASE, {'nome': 'X', 'porcentagem_desconto_4': '10'}, format='json')
        self.assertIn('porcentagem_desconto_4', legado.json()['erro']['campos'])
        iphone = cliente.post(URL_BASE, {'nome': 'X', 'pode_vender_iphone': True}, format='json')
        self.assertIn('pode_vender_iphone', iphone.json()['erro']['campos'])
        contrato = cliente.post(URL_BASE, {'nome': 'X', 'contrato': {'blocks': 'x'}}, format='json')
        self.assertIn('contrato', contrato.json()['erro']['campos'])

    def test_administrador_altera_campo_restrito_e_logo(self):
        user = criar_usuario('adm', permissoes=('vendas.change_loja', 'vendas.view_loja'),
                             grupos=('ADMINISTRADOR',), lojas=(self.loja,))
        cliente = cliente_logado(user)
        resposta = cliente.patch(f'{URL_BASE}{self.loja.pk}/', {'pode_vender_iphone': 'true', 'logo_loja': imagem_png()},
                                 format='multipart')
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.loja.refresh_from_db()
        self.assertTrue(self.loja.pode_vender_iphone)
        self.assertTrue(resposta.json()['url_logo'].startswith('/api/bo/v1/lojas/'))
        self.assertEqual(cliente.get(resposta.json()['url_logo']).status_code, 200)
        registro = ultima_auditoria('loja_alterada')
        self.assertIn('pode_vender_iphone', registro.dados['alteracoes'])
        falsa = cliente.patch(f'{URL_BASE}{self.loja.pk}/',
                              {'logo_loja': imagem_png().__class__('x.png', b'nao e imagem')}, format='multipart')
        self.assertEqual(falsa.status_code, 400)

    def test_editar_fora_do_escopo_404(self):
        outra = criar_loja('Beta')
        cliente = cliente_logado(criar_usuario('ed', permissoes=('vendas.change_loja',), lojas=(self.loja,)))
        self.assertEqual(cliente.patch(f'{URL_BASE}{outra.pk}/', {'nome': 'Y'}, format='json').status_code, 404)

    def test_replicar_qrcode(self):
        url = f'{URL_BASE}{self.loja.pk}/replicar-qrcode/'
        sem_grupo = cliente_logado(criar_usuario('ed', permissoes=('vendas.change_loja',), lojas=(self.loja,)))
        self.assertEqual(sem_grupo.post(url).status_code, 403)
        admin = cliente_logado(criar_usuario('adm', permissoes=('vendas.change_loja',), grupos=('ADMINISTRADOR',),
                                             lojas=(self.loja,)))
        self.assertEqual(admin.get(url).status_code, 405)
        self.assertEqual(admin.post(url).status_code, 422)
        self.loja.qr_code_aplicativo = 'qr_codes_aplicativo/qr.png'
        self.loja.codigo_aplicativo = 'ABC'
        self.loja.save()
        destino = criar_loja('Beta')
        resposta = admin.post(url)
        self.assertEqual(resposta.status_code, 200)
        destino.refresh_from_db()
        self.assertEqual(destino.codigo_aplicativo, 'ABC')
        self.assertEqual(ultima_auditoria('loja_qrcode_replicado').dados['lojas_alteradas'], 1)
        self.assertFalse(Repasse.objects.exists())
