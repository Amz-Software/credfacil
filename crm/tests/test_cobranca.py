"""Régua de cobrança, telefones do cliente, horário comercial e as novas ferramentas do assistente."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.base import ContentFile
from django.utils import timezone

from crm.models import (ConfiguracaoCRM, Conversa, EncaminhamentoIA, Mensagem, Midia, TelefoneCliente,
                        TentativaContato)
from crm.services import aberturas, cobranca, contatos, expediente
from crm.services.assistente import historico, ia, instrucoes
from crm.services.conversas import ConflitoCRM
from crm.services.envio import aplicar_status
from crm.tests.test_assistente import IDENTIDADE_CERTA, AssistenteBase, ferramenta, texto
from vendas.models import ComprovanteParcela, ContatoAdicional, Parcela

CORPO_AVISO = 'Olá, {nome}! Sua parcela de {valor} vence em {vencimento}. Responda se precisar do PIX.'
CORPO_QUITACAO = 'Parabéns, {nome}! Seu contrato está quitado. Responda se quiser um aparelho novo.'
Tipo = TentativaContato.Tipo


def momento(dia: date, hora: int = 10) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time(hora)))


class CobrancaBase(AssistenteBase):
    """Nenhum teste fala com a API: sem roteiro próprio, o modelo responde sempre um texto curto."""

    def setUp(self):
        super().setUp()
        padrao = mock.patch.object(ia, 'chamar', return_value=texto('Oi! Como posso ajudar?'))
        padrao.start()
        self.addCleanup(padrao.stop)


class ExpedienteTests(CobrancaBase):
    def setUp(self):
        super().setUp()
        self.config = ConfiguracaoCRM.obter()

    def test_dias_uteis_sabado_domingo_e_feriados(self):
        segunda = date(2026, 11, 23)
        sabado, domingo = date(2026, 11, 28), date(2026, 11, 29)

        self.assertTrue(expediente.aberto(momento(segunda, 10), self.config))
        self.assertFalse(expediente.aberto(momento(segunda, 19), self.config))
        self.assertTrue(expediente.aberto(momento(sabado, 17), self.config))
        self.assertFalse(expediente.aberto(momento(sabado, 18), self.config))
        self.assertFalse(expediente.aberto(momento(domingo, 10), self.config))
        self.assertFalse(expediente.aberto(momento(date(2026, 12, 25), 10), self.config))
        self.assertFalse(expediente.aberto(momento(date(2027, 3, 26), 10), self.config))  # Sexta-feira Santa

    def test_proxima_abertura_pula_domingo(self):
        proxima = expediente.proxima_abertura(momento(date(2026, 11, 28), 19), self.config)

        self.assertEqual(timezone.localtime(proxima).replace(tzinfo=None), datetime(2026, 11, 30, 8, 0))
        self.assertIn('FORA do horário', expediente.descrever(momento(date(2026, 11, 28), 19), self.config))


class MarcadoresTests(CobrancaBase):
    def test_aceita_nome_valor_vencimento_e_numera_na_ordem(self):
        self.assertEqual(aberturas.validar_corpo(CORPO_AVISO), [])
        corpo_meta, mapa = aberturas._para_meta(CORPO_AVISO)

        self.assertEqual(mapa, ['nome', 'valor', 'vencimento'])
        self.assertIn('{{1}}', corpo_meta)
        self.assertIn('{{3}}', corpo_meta)

    def test_recusa_marcador_desconhecido_e_repetido(self):
        self.assertTrue(aberturas.validar_corpo('Olá {nome}, seu {cpf} está aqui para conferência hoje.'))
        self.assertTrue(aberturas.validar_corpo('Olá {nome}, parcela {valor} e mais {valor} para pagar hoje.'))

    def test_template_de_cobranca_nao_sai_pela_equipe(self):
        modelo = self.abertura_aprovada('Lembrete', CORPO_AVISO)
        conversa = self.receber('oi', wamid='w1').conversa

        disponivel = next(item for item in aberturas.disponiveis() if item['chave'] == modelo.chave)
        self.assertFalse(disponivel['disponivel'])
        self.assertTrue(disponivel['so_cobranca'])
        Conversa.objects.filter(pk=conversa.pk).update(ultima_entrada_em=timezone.now() - timedelta(days=2))
        conversa.refresh_from_db()
        with self.assertRaises(ConflitoCRM):
            aberturas.enviar_abertura(conversa, self.atendente, modelo.chave, 'Maria')


class TelefonesTests(CobrancaBase):
    def setUp(self):
        super().setUp()
        self.cliente.contato_adicional = ContatoAdicional.objects.create(nome_adicional='João', contato='91988887777')
        self.cliente.save()

    def test_sincroniza_cadastro_e_referencia_e_aviso_vai_para_o_principal(self):
        telefones = contatos.sincronizar(self.cliente)

        self.assertEqual({t.origem for t in telefones}, {TelefoneCliente.Origem.CADASTRO,
                                                         TelefoneCliente.Origem.REFERENCIA})
        self.assertEqual(contatos.para_aviso(self.cliente).telefone, '91999990000')
        self.assertEqual(len(contatos.sincronizar(self.cliente)), 2)  # idempotente

    def test_referencia_e_c4m_nao_validado_nunca_recebem_aviso(self):
        principal = contatos.para_aviso(self.cliente)
        contatos.mudar_situacao(principal, TelefoneCliente.Situacao.SEM_WHATSAPP)
        c4m = contatos.adicionar_telefone(self.cliente, '(91) 97777-6666', TelefoneCliente.Origem.C4M, self.gestor)

        self.assertIsNone(contatos.para_aviso(self.cliente))
        contatos.mudar_situacao(c4m, TelefoneCliente.Situacao.VALIDO)
        self.assertEqual(contatos.para_aviso(self.cliente).pk, c4m.pk)

    def test_resultado_de_referencia_so_em_numero_de_referencia(self):
        principal = contatos.para_aviso(self.cliente)
        with self.assertRaises(contatos.ErroContato):
            contatos.registrar_tentativa(principal, TentativaContato.Resultado.REFERENCIA_SEM_SUCESSO, self.gestor)

        contatos.registrar_tentativa(principal, TentativaContato.Resultado.BLOQUEIO_CONFIRMADO, self.gestor)
        principal.refresh_from_db()
        self.assertEqual(principal.situacao, TelefoneCliente.Situacao.BLOQUEADO)

    def test_status_de_contato(self):
        desde = timezone.now() - timedelta(days=1)
        self.assertEqual(contatos.ficha(self.cliente, desde).status, contatos.Status.SEM_TENTATIVA)

        principal = contatos.para_aviso(self.cliente)
        contatos.registrar_tentativa(principal, TentativaContato.Resultado.NAO_ATENDEU, self.gestor)
        self.assertEqual(contatos.ficha(self.cliente, desde).status, contatos.Status.AGUARDANDO_RETORNO)

        contatos.registrar_tentativa(principal, TentativaContato.Resultado.NUMERO_INVALIDO, self.gestor)
        referencia = self.cliente.telefones_crm.get(origem=TelefoneCliente.Origem.REFERENCIA)
        contatos.registrar_tentativa(referencia, TentativaContato.Resultado.REFERENCIA_SEM_SUCESSO, self.gestor)
        self.assertEqual(contatos.ficha(self.cliente, desde).status, contatos.Status.NAO_LOCALIZADO)


class ReguaBase(CobrancaBase):
    def setUp(self):
        super().setUp()
        self.hoje = timezone.localdate()
        modelo = self.abertura_aprovada('Aviso de parcela', CORPO_AVISO)
        quitacao = self.abertura_aprovada('Quitação', CORPO_QUITACAO)
        ConfiguracaoCRM.objects.filter(pk=1).update(
            cobranca_ativa=True, cobranca_ativada_em=timezone.now() - timedelta(days=1),
            cobranca_hora_envio=time(9, 0), modelo_aviso_antes=modelo, modelo_aviso_dia=modelo,
            modelo_aviso_apos=modelo, modelo_aviso_insistencia=modelo, modelo_aviso_quitacao=quitacao)
        self.parcelas = list(Parcela.objects.filter(pagamento=self.pagamento).order_by('numero_parcela'))

    def vencer_em(self, parcela, dias: int) -> Parcela:
        Parcela.objects.filter(pk=parcela.pk).update(data_vencimento=self.hoje + timedelta(days=dias))
        parcela.refresh_from_db()
        return parcela

    def rodar(self, dia: date | None = None, hora: int = 10) -> dict:
        with self.captureOnCommitCallbacks(execute=True):
            return cobranca.rodar(momento(dia or self.hoje, hora), forcar=True)


class ReguaTests(ReguaBase):
    def test_lembrete_tres_dias_antes_sai_uma_vez_com_valor_e_vencimento(self):
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        parcela = self.vencer_em(self.parcelas[2], 3)

        self.assertEqual(self.rodar(), {Tipo.AVISO_ANTES: 1})
        self.assertEqual(self.rodar(), {})

        mensagem = Mensagem.objects.get(origem=Mensagem.Origem.COBRANCA)
        self.assertIn('R$ 100,00', mensagem.texto)
        self.assertIn(parcela.data_vencimento.strftime('%d/%m/%Y'), mensagem.texto)
        self.assertIn('Maria', mensagem.texto)
        self.assertEqual(mensagem.conversa.clientes.get(), self.cliente)
        self.assertEqual(mensagem.conversa.modo, Conversa.Modo.AUTOMATICO)
        tentativa = TentativaContato.objects.get()
        self.assertEqual((tentativa.tipo, tentativa.mensagem_id), (Tipo.AVISO_ANTES, mensagem.pk))

    def test_atraso_antigo_nao_e_disparado_e_pagamento_informado_nao_e_cobrado(self):
        self.vencer_em(self.parcelas[2], 0)
        Parcela.objects.filter(pk=self.parcelas[2].pk).update(pagamento_efetuado=True)

        self.assertEqual(self.rodar(), {})  # a parcela vencida há 10 dias também fica de fora

    def test_um_aviso_por_cliente_por_dia(self):
        self.vencer_em(self.parcelas[1], 0)
        self.vencer_em(self.parcelas[2], 3)

        self.assertEqual(sum(self.rodar().values()), 1)

    def test_antes_do_horario_ou_desligada_nao_envia(self):
        self.vencer_em(self.parcelas[2], 3)

        self.assertEqual(self.rodar(hora=7), {})
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_ativa=False)
        self.assertEqual(self.rodar(), {})

    def test_insistencia_ate_o_cliente_responder(self):
        Parcela.objects.filter(pk=self.parcelas[2].pk).update(pago=True)
        parcela = self.vencer_em(self.parcelas[1], -10)
        telefone = contatos.para_aviso(self.cliente)
        pedido = TentativaContato.objects.create(cliente=self.cliente, telefone=telefone, numero=telefone.telefone,
                                                 tipo=Tipo.AVISO_APOS, parcela=parcela)
        TentativaContato.objects.filter(pk=pedido.pk).update(criado_em=timezone.now() - timedelta(days=6))

        self.assertEqual(self.rodar(), {Tipo.AVISO_INSISTENCIA: 1})
        aviso = TentativaContato.objects.get(tipo=Tipo.AVISO_INSISTENCIA)
        self.assertEqual(aviso.sequencia, 1)

        self.receber('já paguei', telefone='5591999990000', wamid='resp1')
        aviso.refresh_from_db()
        self.assertEqual(aviso.resultado, TentativaContato.Resultado.RESPONDEU)
        TentativaContato.objects.filter(pk=aviso.pk).update(criado_em=timezone.now() - timedelta(days=6))
        self.assertEqual(self.rodar(), {})

    def test_meta_sem_whatsapp_marca_o_numero_e_a_tentativa(self):
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        self.vencer_em(self.parcelas[2], 3)
        self.rodar()
        mensagem = Mensagem.objects.get(origem=Mensagem.Origem.COBRANCA)

        aplicar_status(mensagem.wa_message_id, 'failed', [{'code': 131026, 'title': 'Undeliverable'}])

        tentativa = TentativaContato.objects.get()
        self.assertEqual(tentativa.resultado, TentativaContato.Resultado.SEM_WHATSAPP)
        self.assertEqual(tentativa.telefone.situacao, TelefoneCliente.Situacao.NAO_VERIFICADO)  # pode ser passageiro

        # Segunda falha, em outro dia: aí o número sai da régua.
        TentativaContato.objects.filter(pk=tentativa.pk).update(criado_em=timezone.now() - timedelta(days=2))
        outra = Mensagem.objects.create(conversa=mensagem.conversa, direcao=Mensagem.Direcao.SAIDA,
                                        autor=Mensagem.Autor.AUTOMATICO, origem=Mensagem.Origem.COBRANCA,
                                        status=Mensagem.Status.ENVIADO, wa_message_id='wamid.segunda', texto='aviso')
        TentativaContato.objects.create(cliente=self.cliente, telefone=tentativa.telefone, numero=tentativa.numero,
                                        tipo=Tipo.AVISO_DIA, parcela=self.parcelas[2], mensagem=outra)
        aplicar_status('wamid.segunda', 'failed', [{'code': 131026, 'title': 'Undeliverable'}])
        tentativa.telefone.refresh_from_db()
        self.assertEqual(tentativa.telefone.situacao, TelefoneCliente.Situacao.SEM_WHATSAPP)

    def test_quitacao_sai_uma_vez_quando_a_ultima_parcela_e_paga(self):
        Parcela.objects.filter(pagamento=self.pagamento).update(pago=True, data_pagamento=self.hoje)

        self.assertEqual(self.rodar(), {Tipo.AVISO_QUITACAO: 1})
        self.assertEqual(self.rodar(), {})
        self.assertIn('quitado', Mensagem.objects.get(origem=Mensagem.Origem.COBRANCA).texto)

    def test_aviso_no_historico_da_ia_esconde_valor_sem_identificacao(self):
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        self.vencer_em(self.parcelas[2], 3)
        self.rodar()
        conversa = Conversa.objects.get()
        Mensagem.objects.create(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA, autor=Mensagem.Autor.CLIENTE,
                                texto='oi', processada=True)

        blocos = historico.montar(conversa)
        conteudo = ' '.join(str(bloco['content']) for bloco in blocos)

        self.assertIn('aviso automático de cobrança', conteudo)
        self.assertNotIn('R$ 100,00', conteudo)


class FerramentasNovasTests(CobrancaBase):
    def test_cliente_de_outro_numero_fica_registrado_sem_trocar_o_principal(self):
        roteiro = self.com_roteiro(ferramenta('identificar_cliente', IDENTIDADE_CERTA), texto('Pronto, achei você!'))

        self.receber('sou a Maria, meu cpf 529.982.247-25 nasci 17/05/1990', telefone='5591988881111', wamid='w1')

        self.assertIn('"numero_diferente_do_cadastro": true', roteiro.resultado(1)['content'])
        novo = TelefoneCliente.objects.get(origem=TelefoneCliente.Origem.ATENDIMENTO)
        self.assertEqual((novo.telefone, novo.situacao), ('5591988881111', TelefoneCliente.Situacao.NAO_VERIFICADO))
        self.assertNotEqual(contatos.para_aviso(self.cliente).pk, novo.pk)  # só depois que a equipe confirmar
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.telefone, '91999990000')

    def test_antecipacao_calcula_desconto_por_dia(self):
        ConfiguracaoCRM.objects.filter(pk=1).update(antecipacao_percentual_dia=Decimal('0.1'))
        futura = Parcela.objects.filter(pagamento=self.pagamento).order_by('-numero_parcela').first()
        roteiro = self.com_roteiro(ferramenta('identificar_cliente', IDENTIDADE_CERTA),
                                   ferramenta('simular_antecipacao', {'parcela_ids': [futura.pk]}, 'tu_2'),
                                   texto('Adiantando hoje fica R$ 98,00.'))

        self.receber('quero adiantar', wamid='w1')

        resultado = roteiro.resultado(2)['content']
        self.assertIn('"dias_antecipados": 20', resultado)
        self.assertIn('R$ 2,00', resultado)
        self.assertIn('R$ 98,00', resultado)

    def test_antecipacao_sem_regra_manda_transferir(self):
        futura = Parcela.objects.filter(pagamento=self.pagamento).order_by('-numero_parcela').first()
        roteiro = self.com_roteiro(ferramenta('identificar_cliente', IDENTIDADE_CERTA),
                                   ferramenta('simular_antecipacao', {'parcela_ids': [futura.pk]}, 'tu_2'),
                                   texto('Vou confirmar com a equipe.'))

        self.receber('quero adiantar', wamid='w1')

        self.assertTrue(roteiro.resultado(2)['is_error'])
        self.assertIn('ANTECIPACAO', roteiro.resultado(2)['content'])

    def _imagem_do_cliente(self) -> Mensagem:
        conversa = Conversa.objects.get_or_create(telefone='5591999990000')[0]
        mensagem = Mensagem.objects.create(conversa=conversa, direcao=Mensagem.Direcao.ENTRADA,
                                           autor=Mensagem.Autor.CLIENTE, tipo=Mensagem.Tipo.IMAGEM, processada=True)
        midia = Midia(mensagem=mensagem, mime='image/jpeg', status=Midia.Status.OK, tamanho_bytes=4)
        midia.arquivo.save('comprovante.jpg', ContentFile(b'\xff\xd8\xff\xd9'), save=False)
        midia.save()
        return mensagem

    def test_comprovante_e_anexado_e_a_parcela_fica_informada(self):
        imagem = self._imagem_do_cliente()
        parcela = self.parcela_aberta()
        roteiro = self.com_roteiro(ferramenta('identificar_cliente', IDENTIDADE_CERTA),
                                   ferramenta('registrar_comprovante', {'parcela_id': parcela.pk}, 'tu_2'),
                                   texto('Recebi! A equipe confere e dá baixa.'))

        self.receber('segue o comprovante, cpf 529.982.247-25, 17/05/1990', wamid='w1')

        primeira_volta = roteiro.chamadas[0][-1]['content']
        self.assertTrue(any(parte.get('type') == 'image' for parte in primeira_volta))
        parcela.refresh_from_db()
        self.assertTrue(parcela.pagamento_efetuado)
        self.assertFalse(parcela.pago)
        self.assertEqual(ComprovanteParcela.objects.get().parcela, parcela)
        imagem.refresh_from_db()
        self.assertEqual(imagem.dados['comprovante_parcela'], parcela.pk)

    def test_transferencia_fora_do_horario_registra_assunto_e_mensagem(self):
        roteiro = self.com_roteiro(
            ferramenta('transferir_para_atendente', {'assunto': 'NEGOCIACAO', 'motivo': 'Quer parcelar o atraso.'}),
            texto('Estamos fora do horário, amanhã a equipe te chama.'))

        with mock.patch.object(expediente, 'aberto', return_value=False):
            self.receber('quero negociar', wamid='w1')

        encaminhamento = EncaminhamentoIA.objects.get()
        self.assertEqual((encaminhamento.assunto, encaminhamento.fora_do_horario), ('NEGOCIACAO', True))
        self.assertIn('fora do nosso horário', roteiro.resultado(1)['content'])

    def test_instrucoes_trazem_horario_assuntos_e_consulta(self):
        conversa = self.receber('oi', wamid='w0').conversa
        fixo, turno = (bloco['text'] for bloco in instrucoes.montar_system(conversa))

        self.assertIn('das 08:00 às 19:00', fixo)
        self.assertIn('sábados, das 08:00 às 18:00', fixo)
        self.assertIn('IPX Consulta', fixo)
        self.assertIn('DESBLOQUEIO', fixo)
        self.assertTrue('horário comercial' in turno or 'atendendo agora' in turno)


class RobustezReguaTests(ReguaBase):
    def test_recusa_da_meta_desfaz_a_etapa_e_para_a_rodada(self):
        from crm.whatsapp import ErroWhatsApp

        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        self.vencer_em(self.parcelas[2], 3)
        provider = mock.Mock(enviar_template=mock.Mock(side_effect=ErroWhatsApp('token vencido', 190)))
        with mock.patch.object(cobranca, 'obter_provider', return_value=provider):
            self.assertEqual(self.rodar(), {})

        self.assertFalse(TentativaContato.objects.exists())
        self.assertFalse(Mensagem.objects.filter(origem=Mensagem.Origem.COBRANCA).exists())
        self.assertEqual(self.rodar(), {Tipo.AVISO_ANTES: 1})  # na rodada seguinte, sai

    def test_ligar_a_regua_nao_recupera_etapas_de_antes_da_ativacao(self):
        Parcela.objects.filter(pk=self.parcelas[1].pk).update(pago=True)
        self.vencer_em(self.parcelas[2], 2)  # o "3 dias antes" seria ontem
        ConfiguracaoCRM.objects.filter(pk=1).update(cobranca_ativada_em=timezone.now())

        self.assertEqual(self.rodar(), {})

    def test_numero_antigo_do_cadastro_sai_da_regua(self):
        antigo = contatos.para_aviso(self.cliente)
        self.cliente.telefone = '91977776666'
        self.cliente.save()

        contatos.sincronizar(self.cliente)
        antigo.refresh_from_db()

        self.assertEqual((antigo.origem, antigo.situacao),
                         (TelefoneCliente.Origem.OUTRO, TelefoneCliente.Situacao.NAO_VERIFICADO))
        self.assertEqual(contatos.para_aviso(self.cliente).telefone, '91977776666')


class ConfiguracaoCobrancaTests(CobrancaBase):
    def test_gestor_liga_a_regua_e_marca_quando_ligou(self):
        modelo = self.abertura_aprovada('Aviso', CORPO_AVISO)
        gestor = self.web(self.gestor, ajax=False)

        self.assertEqual(gestor.get('/crm/configuracao/cobranca/').status_code, 200)
        resposta = gestor.post('/crm/configuracao/cobranca/', {
            'cobranca_ativa': 'on', 'cobranca_hora_envio': '09:00', 'cobranca_intervalo_dias': 5,
            'cobranca_max_insistencias': 6, 'modelo_aviso_antes': modelo.pk})

        self.assertEqual(resposta.status_code, 302)
        config = ConfiguracaoCRM.obter()
        self.assertTrue(config.cobranca_ativa)
        self.assertIsNotNone(config.cobranca_ativada_em)
        self.assertIsNotNone(cobranca.versao_vigente(config, 'modelo_aviso_antes'))

    def test_atendente_sem_gerencia_nao_entra(self):
        self.assertIn(self.web(self.atendente, ajax=False).get('/crm/configuracao/cobranca/').status_code,
                      (302, 403))
