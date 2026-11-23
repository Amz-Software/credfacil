"""Rotas do módulo crm da API do backoffice (`/api/bo/v1/crm/`). Contrato em `CONTRATO.md`."""
from django.urls import path

from .views import acoes, anotacoes, apoio, caixa, configuracao, envio, midia, simulador

CONVERSA = 'conversas/<int:pk>/'
MENSAGEM = 'mensagens/<int:mensagem_id>/'
CONFIG = 'configuracao/'

urlpatterns = [
    # Apoio da caixa de entrada
    path('contexto/', apoio.ContextoView.as_view(), name='contexto'),
    path('etiquetas/', apoio.EtiquetasView.as_view(), name='etiquetas'),
    path('respostas-rapidas/', apoio.RespostasRapidasView.as_view(), name='respostas-rapidas'),
    path('aberturas/', apoio.AberturasView.as_view(), name='aberturas'),
    path('atendentes/', apoio.AtendentesView.as_view(), name='atendentes'),
    path('clientes/', apoio.ClientesView.as_view(), name='clientes'),
    # Conversas
    path('conversas/', caixa.ConversasView.as_view(), name='conversas'),
    path('conversas/iniciar/', caixa.IniciarView.as_view(), name='iniciar'),
    path(CONVERSA, caixa.ConversaView.as_view(), name='conversa'),
    path(f'{CONVERSA}ler/', caixa.LerView.as_view(), name='ler'),
    path(f'{CONVERSA}mensagens/', caixa.MensagensView.as_view(), name='mensagens'),
    # Posse, situação e organização
    path(f'{CONVERSA}assumir/', acoes.AssumirView.as_view(), name='assumir'),
    path(f'{CONVERSA}puxar/', acoes.PuxarView.as_view(), name='puxar'),
    path(f'{CONVERSA}atribuir/', acoes.AtribuirView.as_view(), name='atribuir'),
    path(f'{CONVERSA}devolver/', acoes.DevolverView.as_view(), name='devolver'),
    path(f'{CONVERSA}situacao/', acoes.SituacaoView.as_view(), name='situacao'),
    path(f'{CONVERSA}etiquetas/', acoes.EtiquetasConversaView.as_view(), name='conversa-etiquetas'),
    path(f'{CONVERSA}apelido/', acoes.ApelidoView.as_view(), name='apelido'),
    path(f'{CONVERSA}vincular-cliente/', acoes.VincularClienteView.as_view(), name='vincular-cliente'),
    path(f'{CONVERSA}desvincular-cliente/', acoes.DesvincularClienteView.as_view(), name='desvincular-cliente'),
    path(f'{CONVERSA}abrir/', acoes.AbrirView.as_view(), name='abrir'),
    # Envio e textos prontos
    path(f'{CONVERSA}enviar/', envio.EnviarView.as_view(), name='enviar'),
    path(f'{CONVERSA}digitando/', envio.DigitandoView.as_view(), name='digitando'),
    path(f'{CONVERSA}resumo-pagamentos/', envio.ResumoPagamentosView.as_view(), name='resumo-pagamentos'),
    path(f'{CONVERSA}respostas-rapidas/<int:resposta_id>/previa/', envio.PreviaRespostaView.as_view(),
         name='previa-resposta'),
    path(f'{MENSAGEM}reenviar/', envio.ReenviarView.as_view(), name='reenviar'),
    path(f'{MENSAGEM}reagir/', envio.ReagirView.as_view(), name='reagir'),
    path(f'{MENSAGEM}arquivo/', midia.MidiaView.as_view(), name='mensagem-arquivo'),
    # Notas, lembrete e programadas
    path(f'{CONVERSA}notas/', anotacoes.NotasView.as_view(), name='notas'),
    path(f'{CONVERSA}notas/<int:nota_id>/apagar/', anotacoes.ApagarNotaView.as_view(), name='apagar-nota'),
    path(f'{CONVERSA}lembrete/', anotacoes.LembreteView.as_view(), name='lembrete'),
    path(f'{CONVERSA}lembrete/concluir/', anotacoes.ConcluirLembreteView.as_view(), name='concluir-lembrete'),
    path(f'{CONVERSA}programadas/', anotacoes.ProgramadasView.as_view(), name='programadas'),
    path('programadas/<int:programada_id>/cancelar/', anotacoes.CancelarProgramadaView.as_view(),
         name='cancelar-programada'),
    # Configuração (crm.gerenciar_crm)
    path(CONFIG, configuracao.ConfiguracaoView.as_view(), name='configuracao'),
    path(f'{CONFIG}etiquetas/', configuracao.EtiquetasConfigView.as_view(), name='config-etiquetas'),
    path(f'{CONFIG}etiquetas/<int:pk>/', configuracao.EtiquetaConfigView.as_view(), name='config-etiqueta'),
    path(f'{CONFIG}respostas-rapidas/', configuracao.RespostasConfigView.as_view(), name='config-respostas'),
    path(f'{CONFIG}respostas-rapidas/<int:pk>/', configuracao.RespostaConfigView.as_view(), name='config-resposta'),
    path(f'{CONFIG}aberturas/', configuracao.AberturasConfigView.as_view(), name='config-aberturas'),
    path(f'{CONFIG}aberturas/<int:pk>/', configuracao.AberturaConfigView.as_view(), name='config-abertura'),
    path(f'{CONFIG}aberturas/<int:pk>/verificar/', configuracao.AberturaVerificarView.as_view(),
         name='config-abertura-verificar'),
    path(f'{CONFIG}aberturas/<int:pk>/simular/', configuracao.AberturaSimularView.as_view(),
         name='config-abertura-simular'),
    path(f'{CONFIG}simulador/', simulador.SimuladorView.as_view(), name='simulador'),
    path(f'{CONFIG}simulador/receber/', simulador.SimuladorReceberView.as_view(), name='simulador-receber'),
    path(f'{CONFIG}simulador/ler/', simulador.SimuladorLerView.as_view(), name='simulador-ler'),
]
