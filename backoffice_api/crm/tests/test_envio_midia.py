"""Envio de arquivo (válido e inválido), mídia com Range e log, reação, reenvio, digitando e prévia."""
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from crm.models import LogAcessoMidia, Mensagem, RespostaRapida

from .base import CrmApiTestCase, png, url


class EnvioArquivoTests(CrmApiTestCase):
    def _enviar(self, conversa, dados, usuario=None):
        with self.em_commit():
            return self.api(usuario).post(url(f'conversas/{conversa.pk}/enviar/'), dados, format='multipart')

    def test_imagem_com_legenda_e_mídia_autenticada(self):
        conversa = self.conversa_com_humano()

        resposta = self._enviar(conversa, {'arquivo': SimpleUploadedFile('foto.png', png()), 'texto': 'Veja'})

        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        self.assertEqual((dados['tipo'], dados['texto']), ('IMAGEM', 'Veja'))
        self.assertEqual(dados['midia']['mime'], 'image/png')
        self.assertEqual(dados['midia']['url'], f'/api/bo/v1/crm/mensagens/{dados["id"]}/arquivo/')
        mensagem = Mensagem.objects.get(pk=dados['id'])
        self.assertEqual(mensagem.status, Mensagem.Status.ENVIADO)  # saiu em segundo plano após o commit
        listada = self.api().get(url(f'conversas/{conversa.pk}/mensagens/')).json()['results'][-1]
        self.assertEqual(listada['midia']['url'], dados['midia']['url'])
        self.assertIsNone(listada['midia']['url_miniatura'])  # miniatura só nas recebidas (gerada no download)

    def test_arquivo_invalido_recebe_400_em_arquivo(self):
        conversa = self.conversa_com_humano()
        heic = b'\x00\x00\x00\x18ftypheic' + b'\x00' * 64

        resposta = self._enviar(conversa, {'arquivo': SimpleUploadedFile('foto.heic', heic)})

        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(self.erro(resposta)['codigo'], 'validacao')
        self.assertIn('HEIC', self.erro(resposta)['campos']['arquivo'][0])
        self.assertFalse(Mensagem.objects.filter(direcao='SAIDA', autor='HUMANO').exists())

    def test_arquivo_vazio_grande_ou_texto_vazio(self):
        conversa = self.conversa_com_humano()

        vazio = self._enviar(conversa, {'arquivo': SimpleUploadedFile('a.pdf', b'')})
        with mock.patch('crm.services.midias.LIMITE_ENVIO', 10):
            grande = self._enviar(conversa, {'arquivo': SimpleUploadedFile('a.pdf', b'%PDF' + b'0' * 20)})
        sem_texto = self.api().post(url(f'conversas/{conversa.pk}/enviar/'), {'texto': '   '}, format='json')

        self.assertEqual((vazio.status_code, grande.status_code, sem_texto.status_code), (400, 400, 400))
        self.assertIn('arquivo', self.erro(vazio)['campos'])
        self.assertIn('25 MB', self.erro(grande)['campos']['arquivo'][0])
        self.assertIn('texto', self.erro(sem_texto)['campos'])

    def test_voz_so_para_audio_e_trava_de_dono(self):
        conversa = self.conversa_com_humano()

        voz = self._enviar(conversa, {'arquivo': SimpleUploadedFile('foto.png', png()), 'voz': '1'})
        de_outro = self._enviar(conversa, {'arquivo': SimpleUploadedFile('foto.png', png())}, usuario=self.outro)

        self.assertEqual(voz.status_code, 409)
        self.assertEqual(de_outro.status_code, 409)
        self.assertEqual(self.erro(de_outro)['motivo'], 'OUTRO_DONO')


class MidiaTests(CrmApiTestCase):
    def setUp(self):
        super().setUp()
        self.conversa = self.conversa_com_humano()
        with self.em_commit():
            self.api().post(url(f'conversas/{self.conversa.pk}/enviar/'),
                            {'arquivo': SimpleUploadedFile('foto.png', png())}, format='multipart')
        self.mensagem = Mensagem.objects.get(tipo=Mensagem.Tipo.IMAGEM)
        self.url = url(f'mensagens/{self.mensagem.pk}/arquivo/')

    def test_original_registra_acesso_e_miniatura_nao(self):
        miniatura = self.api().get(self.url, {'versao': 'miniatura'})
        original = self.api().get(self.url)

        self.assertEqual((miniatura.status_code, original.status_code), (200, 200))
        self.assertEqual(miniatura['Content-Type'], 'image/jpeg')
        self.assertEqual(original['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(LogAcessoMidia.objects.count(), 1)
        self.assertEqual(LogAcessoMidia.objects.get().usuario, self.atendente)

    def test_range_responde_206(self):
        parcial = self.api().get(self.url, HTTP_RANGE='bytes=0-9')

        self.assertEqual(parcial.status_code, 206)
        self.assertEqual(len(b''.join(parcial.streaming_content)), 10)
        self.assertTrue(parcial['Content-Range'].startswith('bytes 0-9/'))

    def test_sem_acesso_e_mensagem_sem_midia(self):
        texto = Mensagem.objects.filter(conversa=self.conversa, tipo='TEXTO').first()

        self.assertEqual(self.api(self.sem_acesso).get(self.url).status_code, 403)
        sem_midia = self.api().get(url(f'mensagens/{texto.pk}/arquivo/'))
        self.assertEqual(sem_midia.status_code, 404)
        self.assertEqual(self.erro(sem_midia)['codigo'], 'nao_encontrado')
        self.assertEqual(LogAcessoMidia.objects.count(), 0)


class OutrasAcoesTests(CrmApiTestCase):
    def test_reagir_reenviar_e_digitando(self):
        conversa = self.conversa_com_humano()
        recebida = Mensagem.objects.get(conversa=conversa, direcao='ENTRADA')
        falha = Mensagem.objects.create(conversa=conversa, direcao='SAIDA', autor='HUMANO', texto='Falhou',
                                        status='ERRO', erro='Número inválido', usuario=self.atendente)
        api = self.api()

        reacao = api.post(url(f'mensagens/{recebida.pk}/reagir/'), {'emoji': '👍'}, format='json')
        reenvio = api.post(url(f'mensagens/{falha.pk}/reenviar/'))
        de_novo = api.post(url(f'mensagens/{falha.pk}/reenviar/'))
        digitando = api.post(url(f'conversas/{conversa.pk}/digitando/'))

        self.assertEqual(reacao.json()['reacao_equipe'], '👍')
        self.assertEqual(reenvio.json()['status'], 'ENVIADO')
        self.assertEqual(de_novo.status_code, 409)
        self.assertEqual(digitando.status_code, 204)

    def test_previa_de_resposta_rapida(self):
        conversa = self.conversa_com_humano()
        resposta = RespostaRapida.objects.create(atalho='oi', titulo='Saudação',
                                                 texto='Olá {primeiro_nome}, sou {atendente} da {empresa}.')
        inativa = RespostaRapida.objects.create(atalho='velha', titulo='Velha', texto='x', ativo=False)
        api = self.api()

        previa = api.get(url(f'conversas/{conversa.pk}/respostas-rapidas/{resposta.pk}/previa/')).json()
        desativada = api.get(url(f'conversas/{conversa.pk}/respostas-rapidas/{inativa.pk}/previa/'))

        self.assertEqual(previa['texto'], f'Olá Maria, sou {self.atendente.first_name} da IPX.')
        self.assertEqual(previa['avisos'], [])
        self.assertEqual(desativada.status_code, 404)
