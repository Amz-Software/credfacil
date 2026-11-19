"""Rotas do CRM no backoffice (/crm/). Só o webhook da Meta fica em /api/."""
from django.urls import path

from crm.web import acoes, anotacoes, caixa, configuracao, mensagens, midia

app_name = 'crm'

conversa = 'conversas/<int:pk>/'

urlpatterns = [
    # Caixa de entrada
    path('', caixa.caixa, name='caixa'),
    path('lista/', caixa.lista, name='lista'),
    path('iniciar/', acoes.iniciar, name='iniciar'),
    path(conversa, caixa.conversa, name='conversa'),
    path(f'{conversa}parte/<str:nome>/', caixa.parte, name='parte'),
    path(f'{conversa}mensagens/', caixa.mensagens_antigas, name='mensagens_antigas'),
    path(f'{conversa}buscar-cliente/', caixa.buscar_cliente, name='buscar_cliente'),
    # Posse, situação e organização
    path(f'{conversa}assumir/', acoes.assumir, name='assumir'),
    path(f'{conversa}puxar/', acoes.puxar, name='puxar'),
    path(f'{conversa}atribuir/', acoes.atribuir, name='atribuir'),
    path(f'{conversa}devolver/', acoes.devolver, name='devolver'),
    path(f'{conversa}situacao/', acoes.situacao, name='situacao'),
    path(f'{conversa}etiquetas/', acoes.etiquetas, name='etiquetas'),
    path(f'{conversa}apelido/', acoes.apelido, name='apelido'),
    path(f'{conversa}vincular-cliente/', acoes.vincular_cliente, name='vincular_cliente'),
    path(f'{conversa}desvincular-cliente/', acoes.desvincular_cliente, name='desvincular_cliente'),
    path(f'{conversa}abrir/', acoes.abrir, name='abrir'),
    # Envio
    path(f'{conversa}enviar/', mensagens.enviar, name='enviar'),
    path(f'{conversa}digitando/', mensagens.digitando, name='digitando'),
    path(f'{conversa}resumo-pagamentos/', mensagens.resumo_pagamentos, name='resumo_pagamentos'),
    path(f'{conversa}respostas-rapidas/<int:resposta_id>/previa/', mensagens.previa_resposta,
         name='previa_resposta'),
    path('mensagens/<int:mensagem_id>/reenviar/', mensagens.reenviar, name='reenviar'),
    path('mensagens/<int:mensagem_id>/reagir/', mensagens.reagir, name='reagir'),
    path('mensagens/<int:mensagem_id>/arquivo/', midia.midia, name='midia'),
    # Notas, lembrete e programadas
    path(f'{conversa}notas/', anotacoes.criar_nota, name='criar_nota'),
    path(f'{conversa}notas/<int:nota_id>/apagar/', anotacoes.apagar_nota, name='apagar_nota'),
    path(f'{conversa}lembrete/', anotacoes.definir_lembrete, name='definir_lembrete'),
    path(f'{conversa}lembrete/concluir/', anotacoes.concluir_lembrete, name='concluir_lembrete'),
    path(f'{conversa}programadas/', anotacoes.programar, name='programar'),
    path('programadas/<int:programada_id>/cancelar/', anotacoes.cancelar_programada, name='cancelar_programada'),
    # Configuração (gerenciar)
    *configuracao.urlpatterns,
]
