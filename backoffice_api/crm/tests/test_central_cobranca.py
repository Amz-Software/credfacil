"""Central de cobrança na API: permissões, saúde, configuração, pausa, agenda, histórico e disparos."""
import contextlib
import io
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.utils import timezone

from crm.models import ConfiguracaoCRM, DisparoCobranca, TentativaContato
from crm.services import cobranca
from crm.services.central_cobranca import envio_disparos, teto
from crm.tests.fabrica_cobranca import criar_cliente, criar_parcelas
from crm.tests.test_cobranca import CORPO_AVISO, proximo_dia_de_cobranca
from vendas.models import Loja

from .base import CrmApiTestCase, url

VER_CLIENTES = ('vendas.view_cliente', 'vendas.can_view_all_stores')


def momento(dia: date, hora: int = 10) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time(hora)))


class CentralApiBase(CrmApiTestCase):
    def setUp(self):
        super().setUp()
        teto.limpar_cache()
        self.addCleanup(teto.limpar_cache)
        self.hoje = proximo_dia_de_cobranca(timezone.localdate())
        self.modelo = self.abertura_aprovada('Aviso de parcela', CORPO_AVISO)
        ConfiguracaoCRM.objects.filter(pk=1).update(
            cobranca_ativa=True, cobranca_ativada_em=timezone.now() - timedelta(days=1), cobranca_hora_envio=time(9),
            modelo_aviso_antes=self.modelo, modelo_aviso_dia=self.modelo, modelo_aviso_apos=self.modelo)
        self.gestor = self.dar_permissao(self.gestor, *VER_CLIENTES)
        self.loja = Loja.objects.create(nome='Loja Centro')
        self.cliente = criar_cliente(self.loja, 'Maria Souza', '91999990000', '52998224725')
        self.atrasada = criar_parcelas(self.cliente, self.gestor, [self.hoje - timedelta(days=10)])[0]
        self.antes = criar_parcelas(self.cliente, self.gestor, [self.hoje + timedelta(days=3)])[0]

    def rodar_regua(self):
        with self.captureOnCommitCallbacks(execute=True):
            return cobranca.rodar(momento(self.hoje), forcar=True)


class PermissoesTests(CentralApiBase):
    LEITURA = ['cobranca/saude/', 'cobranca/agenda/', 'cobranca/historico/', 'cobranca/modelos/', 'cobranca/disparos/']
    ESCRITA = [('get', 'cobranca/configuracao/'), ('patch', 'cobranca/configuracao/'), ('post', 'cobranca/pausar/'),
               ('post', 'cobranca/retomar/'), ('post', 'cobranca/disparos/'),
               ('post', 'cobranca/disparos/1/confirmar/'),
               ('post', 'cobranca/disparos/1/cancelar/'), ('post', 'cobranca/disparos/1/retomar/')]

    def test_leitura_com_acessar_e_escrita_so_com_gerenciar(self):
        for caminho in self.LEITURA:
            with self.subTest(caminho=caminho):
                self.assertEqual(self.api(self.atendente).get(url(caminho)).status_code, 200)
                self.assertEqual(self.api(self.sem_acesso).get(url(caminho)).status_code, 403)
        for metodo, caminho in self.ESCRITA:
            with self.subTest(caminho=caminho, metodo=metodo):
                resposta = getattr(self.api(self.atendente), metodo)(url(caminho), {}, format='json')
                self.assertEqual(resposta.status_code, 403)
                self.assertIn('gerencia', self.erro(resposta)['mensagem'])
        self.assertTrue(ConfiguracaoCRM.obter().cobranca_ativa)


class SaudeConfigTests(CentralApiBase):
    def test_saude_com_limite_e_qualidade_da_meta(self):
        provider = mock.Mock(consultar_numero=mock.Mock(return_value={'limite': 'TIER_2K', 'qualidade': 'YELLOW'}))
        with mock.patch.object(teto, 'obter_provider', return_value=provider):
            dados = self.api().get(url('cobranca/saude/?atualizar=true')).json()

        self.assertEqual(dados['numero']['limite_tier'], 'TIER_2K')
        self.assertEqual((dados['teto']['automatico'], dados['teto']['efetivo']), (1600, 1600))
        self.assertEqual(dados['regua']['status'], 'pausada_por_qualidade')
        self.assertFalse(dados['regua']['enviando_agora'])
        self.assertEqual(dados['custo_por_mensagem'], '0.035')

    def test_saude_padrao_sem_meta(self):
        dados = self.api().get(url('cobranca/saude/')).json()

        self.assertEqual((dados['numero']['fonte'], dados['teto']['efetivo']), ('padrao', teto.TETO_PADRAO))
        self.assertTrue(dados['simulado'])
        self.assertIn(dados['regua']['status'], ('ativa', 'antes_da_ativacao'))

    def test_configuracao_le_e_altera_com_validacao_e_auditoria(self):
        api = self.api(self.gestor)

        lida = api.get(url('cobranca/configuracao/')).json()
        invalida = api.patch(url('cobranca/configuracao/'), {'cobranca_teto_diario': 0}, format='json')
        valida = api.patch(url('cobranca/configuracao/'), {'cobranca_teto_diario': 150, 'cobranca_intervalo_dias': 7},
                           format='json')

        self.assertEqual(lida['configuracao']['modelo_aviso_antes'], self.modelo.pk)
        self.assertTrue(next(e for e in lida['etapas'] if e['campo'] == 'modelo_aviso_antes')['pronta'])
        self.assertEqual(invalida.status_code, 400)
        self.assertIn('cobranca_teto_diario', self.erro(invalida)['campos'])
        self.assertEqual(valida.json()['configuracao']['cobranca_teto_diario'], 150)
        self.assertEqual(ConfiguracaoCRM.obter().cobranca_intervalo_dias, 7)
        self.assertEqual(self.auditorias('crm_cobranca_configuracao_alterada').get().dados['campos'],
                         ['cobranca_intervalo_dias', 'cobranca_teto_diario'])
        self.assertEqual(self.api().get(url('cobranca/saude/')).json()['teto']['efetivo'], 150)

    def test_pausar_e_retomar_mantem_a_data_de_ativacao(self):
        api = self.api(self.gestor)
        ativada = ConfiguracaoCRM.obter().cobranca_ativada_em

        pausa = api.post(url('cobranca/pausar/'), {'motivo': 'Revisar textos'}, format='json')
        repetida = api.post(url('cobranca/pausar/'), {}, format='json')
        retomada = api.post(url('cobranca/retomar/'), {}, format='json')

        self.assertEqual(pausa.json()['regua']['status'], 'pausada')
        self.assertEqual(repetida.status_code, 409)
        self.assertEqual(retomada.status_code, 200)
        self.assertEqual(ConfiguracaoCRM.obter().cobranca_ativada_em, ativada)
        self.assertEqual(self.auditorias('crm_cobranca_pausada').get().motivo, 'Revisar textos')
        self.assertEqual(self.auditorias('crm_cobranca_retomada').count(), 1)


class AgendaHistoricoTests(CentralApiBase):
    def test_agenda_por_dia_e_etapa_com_custo(self):
        dados = self.api().get(url('cobranca/agenda/?dias=3')).json()

        self.assertEqual(len(dados['dias']), 4)
        hoje = dados['dias'][0]
        self.assertEqual([e['etapa'] for e in hoje['etapas']], ['quitacao', 'antes', 'dia', 'apos', 'insistencia'])
        if not hoje['bloqueio']:
            antes = next(e for e in hoje['etapas'] if e['etapa'] == 'antes')
            self.assertEqual((antes['previstos'], antes['custo_estimado']), (1, '0.04'))
        self.assertEqual(self.api().get(url('cobranca/agenda/?dias=15')).status_code, 400)

    def test_lista_do_dia_com_escopo_e_validacao_da_data(self):
        caminho = f'cobranca/agenda/{timezone.localdate().isoformat()}/'

        com_escopo = self.api(self.gestor).get(url(caminho)).json()
        sem_escopo = self.api().get(url(caminho)).json()

        self.assertIn('resumo', com_escopo)
        self.assertEqual(sem_escopo['count'], 0)  # atendente sem vendas.view_cliente
        if com_escopo['count']:
            self.assertEqual(com_escopo['results'][0]['telefone'], '(91) *****-0000')
        self.assertEqual(self.api().get(url('cobranca/agenda/2020-01-01/')).status_code, 400)
        self.assertEqual(self.api().get(url('cobranca/agenda/ontem/')).status_code, 400)

    def test_historico_com_resumo_e_filtros(self):
        self.rodar_regua()
        api = self.api(self.gestor)

        dados = api.get(url('cobranca/historico/')).json()
        filtrado = api.get(url('cobranca/historico/?etapa=dia')).json()
        invalido = api.get(url('cobranca/historico/?desde=2026-12-10&ate=2026-12-01'))

        self.assertEqual(dados['count'], 1)
        item = dados['results'][0]
        self.assertEqual((item['etapa'], item['origem'], item['status']), ('antes', 'regua', 'enviado'))
        self.assertEqual(item['telefone'], '(91) *****-0000')
        self.assertIsNotNone(item['conversa_id'])
        self.assertEqual(dados['resumo']['por_etapa'], {'antes': 1})
        self.assertEqual(filtrado['count'], 0)
        self.assertEqual(invalido.status_code, 400)


class DisparosApiTests(CentralApiBase):
    def criar(self, **publico):
        return self.api(self.gestor).post(url('cobranca/disparos/'), {'modelo': self.modelo.pk, **publico},
                                          format='json')

    def test_fluxo_previa_confirmar_enviar_e_historico(self):
        previa = self.criar(atraso_min=5, atraso_max=15)
        disparo_id = previa.json()['id']
        confirmado = self.api(self.gestor).post(url(f'cobranca/disparos/{disparo_id}/confirmar/'))
        with self.captureOnCommitCallbacks(execute=True):
            envio_disparos.processar(momento(self.hoje), forcar=True)
        detalhe = self.api().get(url(f'cobranca/disparos/{disparo_id}/')).json()
        destinatarios = self.api(self.gestor).get(url(f'cobranca/disparos/{disparo_id}/destinatarios/')).json()
        historico = self.api(self.gestor).get(url(f'cobranca/historico/?disparo={disparo_id}')).json()

        self.assertEqual(previa.status_code, 201)
        self.assertEqual((previa.json()['status'], previa.json()['total']), ('PREVIA', 1))
        self.assertIn('Maria', previa.json()['exemplo'])
        self.assertIsNotNone(previa.json()['estimativa'])
        self.assertEqual(confirmado.json()['status'], 'AGENDADO')
        self.assertEqual((detalhe['status'], detalhe['enviados'], detalhe['percentual']), ('CONCLUIDO', 1, 100))
        self.assertIsNone(detalhe['estimativa'])
        self.assertEqual(destinatarios['results'][0]['situacao'], 'ENVIADO')
        self.assertEqual((historico['count'], historico['results'][0]['origem']), (1, 'disparo'))
        self.assertEqual(self.auditorias('crm_disparo_previa').count(), 1)
        self.assertEqual(self.auditorias('crm_disparo_confirmado').count(), 1)

    def test_validacao_do_publico_e_modelo(self):
        sem_criterio = self.criar()
        dois = self.criar(vencimento_dia=10, vencimento_data='2026-12-10')
        incompleto = self.criar(atraso_min=5)
        invertido = self.criar(atraso_min=10, atraso_max=5)
        dia_errado = self.criar(vencimento_dia=15)
        inexistente = self.api(self.gestor).post(url('cobranca/disparos/'), {'modelo': 999, 'vencimento_dia': 10},
                                                 format='json')
        self.modelo.versoes.update(vigente=False)
        nao_aprovado = self.criar(vencimento_dia=10)

        for resposta in (sem_criterio, dois, incompleto, invertido, dia_errado, inexistente):
            self.assertEqual(resposta.status_code, 400)
        self.assertIn('modelo', self.erro(inexistente)['campos'])
        self.assertEqual(nao_aprovado.status_code, 409)

    def test_cancelar_retomar_lista_e_modelos(self):
        disparo_id = self.criar(parcelas=[self.atrasada.pk]).json()['id']
        api = self.api(self.gestor)

        lista_sem_previa = api.get(url('cobranca/disparos/')).json()
        lista_previas = api.get(url('cobranca/disparos/?status=PREVIA')).json()
        cancelado = api.post(url(f'cobranca/disparos/{disparo_id}/cancelar/'))
        de_novo = api.post(url(f'cobranca/disparos/{disparo_id}/cancelar/'))
        retomar = api.post(url(f'cobranca/disparos/{disparo_id}/retomar/'))
        modelos = self.api().get(url('cobranca/modelos/')).json()

        self.assertEqual((lista_sem_previa['count'], lista_previas['count']), (0, 1))
        self.assertEqual(cancelado.json()['status'], 'CANCELADO')
        self.assertEqual((de_novo.status_code, retomar.status_code), (409, 409))
        self.assertEqual(self.auditorias('crm_disparo_cancelado').count(), 1)
        self.assertEqual([m['id'] for m in modelos], [self.modelo.pk])
        self.assertEqual(modelos[0]['marcadores'], ['nome', 'valor', 'vencimento'])
        self.assertEqual(self.api().get(url('cobranca/disparos/999/')).status_code, 404)
        self.assertEqual(DisparoCobranca.objects.get(pk=disparo_id).cancelado_por, self.gestor)

    def test_publico_respeita_as_lojas_de_quem_cria(self):
        so_loja = self.dar_permissao(self.criar_usuario_backoffice('lojista'), 'vendas.view_cliente')

        resposta = self.api(so_loja).post(url('cobranca/disparos/'), {'modelo': self.modelo.pk, 'atraso_min': 5,
                                                                       'atraso_max': 15}, format='json')

        self.assertEqual(resposta.json()['total'], 0)
        self.assertFalse(TentativaContato.objects.exists())

    def criar_usuario_backoffice(self, nome: str):
        from backoffice_api.tests.fabricas import criar_usuario

        return criar_usuario(nome, permissoes=('crm.acessar_crm', 'crm.gerenciar_crm'))


class EsquemaTests(CentralApiBase):
    def test_rotas_no_openapi(self):
        from drf_spectacular.generators import SchemaGenerator

        prefixo = '/api/bo/v1/crm/cobranca/'
        with contextlib.redirect_stderr(io.StringIO()):  # avisos antigos de outras views
            esquema = SchemaGenerator().get_schema(request=None, public=True)
        caminhos = {c.removeprefix(prefixo) for c in esquema['paths'] if c.startswith(prefixo)}

        self.assertEqual(caminhos, {
            'saude/', 'configuracao/', 'pausar/', 'retomar/', 'agenda/', 'agenda/{data}/', 'historico/', 'modelos/',
            'disparos/', 'disparos/{id}/', 'disparos/{id}/destinatarios/', 'disparos/{id}/confirmar/',
            'disparos/{id}/cancelar/', 'disparos/{id}/retomar/'})
