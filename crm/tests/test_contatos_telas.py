"""Telefones e tentativas de contato no painel da conversa."""
from django.contrib.auth.models import Permission

from crm.models import TelefoneCliente, TentativaContato
from crm.tests.base import CrmTestCase
from crm.tests.fabrica_cobranca import criar_cliente
from vendas.models import ContatoAdicional, Loja

Origem = TelefoneCliente.Origem
Situacao = TelefoneCliente.Situacao
Resultado = TentativaContato.Resultado
CONFLITO = 409


class ContatosTelasBase(CrmTestCase):
    def setUp(self):
        super().setUp()
        self.loja = Loja.objects.create(nome='Loja Centro')
        self.cliente = criar_cliente(self.loja, 'Maria Souza', '91999990000', '52998224725')
        self.conversa = self.receber('Oi', wamid='w1').conversa
        self.conversa.clientes.add(self.cliente)
        self.loja.usuarios.add(self.atendente)
        self.atendente.user_permissions.add(
            *Permission.objects.filter(content_type__app_label='vendas', codename='view_cliente'))
        self.web_atendente = self.web(self.criar_usuario_recarregado(self.atendente))
        self.base = f'/crm/conversas/{self.conversa.pk}/'

    def url_telefones(self, cliente_id: int | None = None) -> str:
        return f'{self.base}clientes/{cliente_id or self.cliente.pk}/telefones/'

    def url_tentativas(self) -> str:
        return f'{self.base}clientes/{self.cliente.pk}/tentativas/'

    def principal(self) -> TelefoneCliente:
        return TelefoneCliente.objects.get(cliente=self.cliente, telefone='91999990000')


class PainelContatosTests(ContatosTelasBase):
    def test_painel_mostra_telefones_formatados_e_tentativas(self):
        resposta = self.web_atendente.get(f'{self.base}parte/painel/')

        self.assertContains(resposta, 'Telefones e tentativas')
        self.assertContains(resposta, '+55 (91) 99999-0000')
        self.assertContains(resposta, 'Principal do cadastro')
        self.assertContains(resposta, 'Recebe avisos de cobrança')
        self.assertContains(resposta, 'Nenhuma tentativa registrada.')

    def test_referencia_aparece_so_como_contato_para_ligar(self):
        self.cliente.contato_adicional = ContatoAdicional.objects.create(
            nome_adicional='João Irmão', contato='91988887777', loja=self.loja)
        self.cliente.save()

        resposta = self.web_atendente.get(f'{self.base}parte/painel/')

        self.assertContains(resposta, 'João Irmão')
        self.assertContains(resposta, 'Contato para ligar')
        referencia = TelefoneCliente.objects.get(cliente=self.cliente, origem=Origem.REFERENCIA)
        self.assertEqual(referencia.telefone, '91988887777')


class AdicionarTelefoneTests(ContatosTelasBase):
    def test_numero_do_c4m_entra_nao_verificado(self):
        resposta = self.web_atendente.post(self.url_telefones(), {
            'telefone': '(91) 98111-2222', 'origem': Origem.C4M, 'observacao': 'Achado no C4M'})

        self.assertEqual(resposta.json()['ok'], True)
        novo = TelefoneCliente.objects.get(cliente=self.cliente, origem=Origem.C4M)
        self.assertEqual((novo.telefone, novo.situacao, novo.criado_por), ('91981112222', Situacao.NAO_VERIFICADO,
                                                                         self.atendente))

    def test_numero_repetido_vira_aviso_sem_500(self):
        resposta = self.web_atendente.post(self.url_telefones(), {'telefone': '91999990000', 'origem': Origem.OUTRO})

        self.assertEqual(resposta.status_code, CONFLITO)
        self.assertIn('já está na lista', resposta.json()['erro'])

    def test_numero_curto_sem_js_volta_com_mensagem(self):
        web = self.web(self.criar_usuario_recarregado(self.atendente), ajax=False)

        resposta = web.post(self.url_telefones(), {'telefone': '123', 'origem': Origem.C4M}, follow=True)

        self.assertRedirects(resposta, f'{self.base}')
        self.assertContains(resposta, 'Informe o telefone com DDD')

    def test_cliente_fora_da_conversa_da_404(self):
        outro = criar_cliente(self.loja, 'José', '91977776666', '11144477735')

        resposta = self.web_atendente.post(self.url_telefones(outro.pk), {'telefone': '91981112222',
                                                                         'origem': Origem.C4M})

        self.assertEqual(resposta.status_code, 404)

    def test_sem_acesso_ao_crm_e_negado(self):
        resposta = self.web(self.sem_acesso).post(self.url_telefones(), {'telefone': '91981112222',
                                                                        'origem': Origem.C4M})

        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(TelefoneCliente.objects.filter(origem=Origem.C4M).exists())

    def test_sem_permissao_de_ver_o_cliente_da_404(self):
        resposta = self.web(self.outro).post(self.url_telefones(), {'telefone': '91981112222',
                                                                   'origem': Origem.C4M})

        self.assertEqual(resposta.status_code, 404)

    def test_get_nao_e_aceito(self):
        self.assertEqual(self.web_atendente.get(self.url_telefones()).status_code, 405)


class SituacaoETentativaTests(ContatosTelasBase):
    def test_equipe_confirma_numero_do_c4m(self):
        self.web_atendente.post(self.url_telefones(), {'telefone': '91981112222', 'origem': Origem.C4M})
        novo = TelefoneCliente.objects.get(origem=Origem.C4M)

        resposta = self.web_atendente.post(f'{self.base}telefones/{novo.pk}/situacao/', {'situacao': Situacao.VALIDO})

        novo.refresh_from_db()
        self.assertEqual(resposta.json()['ok'], True)
        self.assertEqual(novo.situacao, Situacao.VALIDO)

    def test_situacao_invalida_vira_aviso(self):
        self.web_atendente.get(f'{self.base}parte/painel/')  # sincroniza os telefones do cadastro

        resposta = self.web_atendente.post(f'{self.base}telefones/{self.principal().pk}/situacao/',
                                           {'situacao': 'XYZ'})

        self.assertEqual(resposta.status_code, CONFLITO)
        self.assertEqual(resposta.json()['erro'], 'Situação inválida.')

    def test_telefone_de_cliente_de_outra_conversa_da_404(self):
        outro = criar_cliente(self.loja, 'José', '91977776666', '11144477735')
        alheio = TelefoneCliente.objects.create(cliente=outro, telefone='91977776666', origem=Origem.CADASTRO)

        resposta = self.web_atendente.post(f'{self.base}telefones/{alheio.pk}/situacao/',
                                           {'situacao': Situacao.BLOQUEADO})

        self.assertEqual(resposta.status_code, 404)

    def test_registrar_tentativa_e_listar_no_painel(self):
        self.web_atendente.get(f'{self.base}parte/painel/')

        resposta = self.web_atendente.post(self.url_tentativas(), {
            'telefone': self.principal().pk, 'canal': 'LIGACAO', 'resultado': Resultado.BLOQUEIO_CONFIRMADO,
            'observacao': 'Disse que bloqueou'})

        self.assertEqual(resposta.json()['ok'], True)
        tentativa = TentativaContato.objects.get()
        self.assertEqual((tentativa.tipo, tentativa.usuario), (TentativaContato.Tipo.MANUAL, self.atendente))
        self.assertEqual(self.principal().situacao, Situacao.BLOQUEADO)
        painel = self.web_atendente.get(f'{self.base}parte/painel/')
        self.assertContains(painel, 'Bloqueio confirmado')
        self.assertContains(painel, 'Disse que bloqueou')

    def test_resultado_de_referencia_em_numero_do_cliente_vira_aviso(self):
        self.web_atendente.get(f'{self.base}parte/painel/')

        resposta = self.web_atendente.post(self.url_tentativas(), {
            'telefone': self.principal().pk, 'resultado': Resultado.REFERENCIA_SEM_SUCESSO})

        self.assertEqual(resposta.status_code, CONFLITO)
        self.assertIn('só vale para número de referência', resposta.json()['erro'])
        self.assertFalse(TentativaContato.objects.exists())

    def test_tentativa_sem_telefone_vira_aviso(self):
        resposta = self.web_atendente.post(self.url_tentativas(), {'resultado': Resultado.NAO_ATENDEU})

        self.assertEqual(resposta.status_code, CONFLITO)
        self.assertEqual(resposta.json()['erro'], 'Escolha o telefone usado na tentativa.')
