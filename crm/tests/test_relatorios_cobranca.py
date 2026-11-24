"""Relatórios e indicadores da cobrança (crm/services/relatorios_cobranca.py) e a tela /crm/cobranca/."""
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.utils import timezone

from crm.models import Conversa, EncaminhamentoIA, Mensagem, TelefoneCliente, TentativaContato
from crm.services import contatos
from crm.services import relatorios_cobranca as relatorios
from crm.services.contatos import Status
from crm.services.relatorios_cobranca import Filtros, Relatorio
from crm.tests.base import CrmTestCase
from crm.tests.fabrica_cobranca import criar_cliente, criar_parcelas
from vendas.models import ComprovanteParcela, ContatoAdicional, Loja, Parcela

Origem = TelefoneCliente.Origem
Situacao = TelefoneCliente.Situacao
Resultado = TentativaContato.Resultado
Tipo = TentativaContato.Tipo
DIA_VENCIMENTO = 10


def ultimo_dia_10(hoje: date) -> date:
    """O dia 10 mais recente antes de hoje (parcela vencida com dia de vencimento 10)."""
    if hoje.day > DIA_VENCIMENTO:
        return hoje.replace(day=DIA_VENCIMENTO)
    anterior = hoje.replace(day=1) - timedelta(days=1)
    return anterior.replace(day=DIA_VENCIMENTO)


class RelatoriosBase(CrmTestCase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        self.vencida = ultimo_dia_10(self.hoje)
        self.loja = Loja.objects.create(nome='Loja Centro')
        self.sem_resposta = self._cliente('Ana Sem Resposta', '91990000001', '52998224725')
        self.bloqueado = self._cliente('Bia Bloqueada', '91990000002', '11144477735')
        self.alternativo = self._cliente('Caio Alternativo', '91990000003', '39053344705')
        self.nao_localizado = self._cliente('Davi Sumido', '91990000004', '87748248800')
        self.respondeu = self._cliente('Eva Respondeu', '91990000005', '12345678909')
        self.fora = criar_cliente(self.loja, 'Fabio Em Dia', '91990000006', '98765432100')
        criar_parcelas(self.fora, self.atendente, [self.hoje + timedelta(days=15)])
        self._montar_cenarios()

    def _cliente(self, nome: str, telefone: str, cpf: str):
        cliente = criar_cliente(self.loja, nome, telefone, cpf)
        cliente.parcelas_teste = criar_parcelas(cliente, self.atendente, [self.vencida])
        return cliente

    def principal(self, cliente) -> TelefoneCliente:
        return next(t for t in contatos.sincronizar(cliente) if t.telefone == cliente.telefone)

    def aviso(self, cliente, status_mensagem: str = Mensagem.Status.ENVIADO) -> TentativaContato:
        telefone = self.principal(cliente)
        conversa = Conversa.objects.create(telefone='55' + telefone.telefone)
        conversa.clientes.add(cliente)
        mensagem = Mensagem.objects.create(conversa=conversa, direcao=Mensagem.Direcao.SAIDA,
                                           autor=Mensagem.Autor.AUTOMATICO, texto='Sua parcela venceu',
                                           status=status_mensagem, origem=Mensagem.Origem.COBRANCA)
        return TentativaContato.objects.create(cliente=cliente, telefone=telefone, numero=telefone.telefone,
                                               tipo=Tipo.AVISO_APOS, parcela=cliente.parcelas_teste[0],
                                               mensagem=mensagem)

    def _montar_cenarios(self):
        self.aviso(self.sem_resposta, Mensagem.Status.LIDO)
        contatos.registrar_tentativa(self.principal(self.bloqueado), Resultado.BLOQUEIO_CONFIRMADO, self.gestor)
        self.aviso(self.alternativo, Mensagem.Status.ENTREGUE)
        contatos.adicionar_telefone(self.alternativo, '91981112222', Origem.C4M, self.gestor,
                                    situacao=Situacao.VALIDO)
        self.nao_localizado.contato_adicional = ContatoAdicional.objects.create(
            nome_adicional='Tio', contato='91977770000', loja=self.loja)
        self.nao_localizado.save()
        contatos.registrar_tentativa(self.principal(self.nao_localizado), Resultado.SEM_WHATSAPP, self.gestor)
        referencia = TelefoneCliente.objects.get(cliente=self.nao_localizado, origem=Origem.REFERENCIA)
        contatos.registrar_tentativa(referencia, Resultado.REFERENCIA_SEM_SUCESSO, self.gestor)
        contatos.registrar_tentativa(self.principal(self.respondeu), Resultado.RESPONDEU, self.gestor)

    def nomes(self, nome_relatorio: str, filtros: Filtros | None = None) -> set[str]:
        resultado = relatorios.relatorio(nome_relatorio, filtros or Filtros.padrao(self.hoje), hoje=self.hoje)
        return {linha.nome for linha in resultado.linhas}


class PopulacaoTests(RelatoriosBase):
    def test_populacao_tem_tentativas_ou_atraso_e_exclui_quem_esta_em_dia(self):
        ids = relatorios.ids_da_populacao(Filtros.padrao(self.hoje), self.hoje)

        self.assertIn(self.sem_resposta.pk, ids)
        self.assertNotIn(self.fora.pk, ids)
        self.assertEqual(len(ids), 5)

    def test_atrasado_sem_tentativa_entra_como_sem_tentativa(self):
        sem_contato = self._cliente('Gil Atrasado', '91990000007', '11122233396')

        itens = dict((c.pk, f) for c, f in relatorios.fichas(Filtros.padrao(self.hoje), self.hoje))

        self.assertEqual(itens[sem_contato.pk].status, Status.SEM_TENTATIVA)

    def test_filtro_por_dia_e_data_de_vencimento(self):
        outro_dia = self.vencida - timedelta(days=1)
        vinte = self._cliente('Hugo Dia Diferente', '91990000008', '22233344405')
        Parcela.objects.filter(pk=vinte.parcelas_teste[0].pk).update(data_vencimento=outro_dia)
        padrao = Filtros.padrao(self.hoje)

        por_dia = relatorios.ids_da_populacao(Filtros(padrao.desde, padrao.ate, dia_vencimento=DIA_VENCIMENTO),
                                              self.hoje)
        por_data = relatorios.ids_da_populacao(Filtros(padrao.desde, padrao.ate, data_vencimento=outro_dia),
                                               self.hoje)

        self.assertNotIn(vinte.pk, por_dia)
        self.assertIn(self.sem_resposta.pk, por_dia)
        self.assertEqual(por_data, {vinte.pk})


class RelatoriosTests(RelatoriosBase):
    def test_sem_resposta_so_quem_recebeu_aviso_e_nao_respondeu(self):
        self.assertEqual(self.nomes(Relatorio.SEM_RESPOSTA), {'Ana Sem Resposta', 'Caio Alternativo'})

    def test_bloqueados_so_com_bloqueio_confirmado(self):
        self.assertEqual(self.nomes(Relatorio.BLOQUEADOS), {'Bia Bloqueada'})

    def test_referencias_sem_sucesso_e_nao_localizados(self):
        self.assertEqual(self.nomes(Relatorio.REFERENCIAS), {'Davi Sumido'})
        self.assertEqual(self.nomes(Relatorio.NAO_LOCALIZADOS), {'Davi Sumido'})

    def test_priorizar_quem_tem_numero_valido_sem_tentativa(self):
        self.assertEqual(self.nomes(Relatorio.PRIORIZAR), {'Caio Alternativo'})

    def test_filtro_de_status_no_todos(self):
        padrao = Filtros.padrao(self.hoje)
        filtros = Filtros(padrao.desde, padrao.ate, status=Status.CONTATO_REALIZADO)

        self.assertEqual(self.nomes(Relatorio.TODOS, filtros), {'Eva Respondeu'})

    def test_linha_traz_atraso_telefone_conversa_e_contagens(self):
        resultado = relatorios.relatorio(Relatorio.SEM_RESPOSTA, Filtros.padrao(self.hoje), hoje=self.hoje)

        linha = next(l for l in resultado.linhas if l.cliente_id == self.sem_resposta.pk)
        self.assertEqual((linha.parcelas_atrasadas, str(linha.total_atrasado)), (1, '100.00'))
        self.assertEqual(linha.telefone, '+55 (91) 99000-0001')
        self.assertEqual(linha.conversa_id, self.sem_resposta.conversas_whatsapp.get().pk)
        self.assertEqual(resultado.contagens[Relatorio.TODOS], 5)
        self.assertEqual(resultado.contagens[Relatorio.BLOQUEADOS], 1)

    def test_paginacao(self):
        self.assertEqual(relatorios.relatorio(Relatorio.TODOS, Filtros.padrao(self.hoje), 99,
                                              hoje=self.hoje).pagina.number, 1)


class IndicadoresTests(RelatoriosBase):
    def test_indicadores_do_periodo(self):
        pago = self.sem_resposta.parcelas_teste[0]
        Parcela.objects.filter(pk=pago.pk).update(pago=True)
        ComprovanteParcela.objects.create(parcela=self.alternativo.parcelas_teste[0],
                                          observacao=relatorios.OBSERVACAO_COMPROVANTE_WHATSAPP,
                                          arquivo=ContentFile(b'%PDF-1.4', name='comprovante.pdf'))
        conversa = self.alternativo.conversas_whatsapp.get()
        EncaminhamentoIA.objects.create(conversa=conversa, assunto=EncaminhamentoIA.Assunto.NEGOCIACAO)
        EncaminhamentoIA.objects.create(conversa=conversa, assunto=EncaminhamentoIA.Assunto.ATENDENTE,
                                        fora_do_horario=True)

        i = relatorios.indicadores(Filtros.padrao(self.hoje), self.hoje)

        self.assertEqual((i.avisos_enviados, i.avisos_entregues, i.avisos_lidos), (2, 2, 1))
        self.assertEqual(i.avisos_por_tipo, [('Pedido de comprovante após o vencimento', 2)])
        self.assertEqual((i.pagamentos_identificados, i.comprovantes_whatsapp), (1, 1))
        self.assertEqual((i.negociacoes, i.encaminhamentos, i.encaminhamentos_fora_do_horario), (1, 2, 1))
        self.assertEqual(i.contatos_alternativos, 1)
        self.assertEqual((i.clientes_responderam, i.clientes_sem_retorno, i.nao_localizados), (1, 2, 1))

    def test_periodo_antigo_nao_conta_avisos(self):
        antigo = Filtros(self.hoje - timedelta(days=90), self.hoje - timedelta(days=60))

        self.assertEqual(relatorios.indicadores(antigo, self.hoje).avisos_enviados, 0)


class TelaCobrancaTests(RelatoriosBase):
    def test_so_quem_gerencia_ve_a_tela(self):
        self.assertEqual(self.web(self.atendente, ajax=False).get('/crm/cobranca/').status_code, 403)
        self.assertEqual(self.web(self.sem_acesso, ajax=False).get('/crm/cobranca/').status_code, 403)

    def _ver_clientes(self, usuario, todas_as_lojas: bool = True):
        from django.contrib.auth.models import Permission

        codigos = ['view_cliente'] + (['view_all_analise_credito'] if todas_as_lojas else [])
        usuario.user_permissions.add(*Permission.objects.filter(content_type__app_label='vendas',
                                                                codename__in=codigos))
        return self.criar_usuario_recarregado(usuario)

    def test_so_ve_clientes_das_lojas_permitidas(self):
        sem_permissao = self.web(self.gestor, ajax=False).get('/crm/cobranca/', {'aba': Relatorio.BLOQUEADOS})
        outra_loja = self.web(self._ver_clientes(self.gestor, todas_as_lojas=False), ajax=False).get(
            '/crm/cobranca/', {'aba': Relatorio.BLOQUEADOS})

        self.assertNotContains(sem_permissao, 'Bia Bloqueada')
        self.assertNotContains(outra_loja, 'Bia Bloqueada')

    def test_painel_e_abas(self):
        web = self.web(self._ver_clientes(self.gestor), ajax=False)

        painel = web.get('/crm/cobranca/')
        bloqueados = web.get('/crm/cobranca/', {'aba': Relatorio.BLOQUEADOS})

        self.assertContains(painel, 'Avisos enviados')
        self.assertContains(painel, 'Atendimentos encaminhados pela IA')
        self.assertContains(bloqueados, 'Bia Bloqueada')
        self.assertNotContains(bloqueados, 'Ana Sem Resposta')
        self.assertContains(bloqueados, 'Bloqueio confirmado')

    def test_filtros_invalidos_voltam_ao_padrao(self):
        resposta = self.web(self.gestor, ajax=False).get('/crm/cobranca/', {
            'aba': 'xyz', 'desde': 'ontem', 'dia': '7', 'status': 'NADA', 'vencimento': '2026-02-31'})

        filtros = resposta.context['filtros']
        self.assertEqual(resposta.context['aba'], 'painel')
        self.assertEqual((filtros.desde, filtros.dia_vencimento, filtros.status, filtros.data_vencimento),
                         (self.hoje - timedelta(days=relatorios.DIAS_PADRAO), None, None, None))

    def test_link_na_caixa_para_quem_gerencia(self):
        self.assertContains(self.web(self.gestor, ajax=False).get('/crm/'), '/crm/cobranca/')
        self.assertNotContains(self.web(self.atendente, ajax=False).get('/crm/'), '/crm/cobranca/')
