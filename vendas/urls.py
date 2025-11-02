from django.contrib import admin
from django.urls import path

from financeiro.views import ContatoCreateView, ContatoUpdateView
from utils.gerador_views import generate_views
from vendas.forms import *
from vendas.models import *
from .views import *

tipoPagamentoViews = generate_views(TipoPagamento, TipoPagamentoForm, 10, template_dir='tipopagamento')

app_name = 'vendas'
urlpatterns = [
    path('', IndexView.as_view(), name='index'),

    #caixa
    path('caixas/', CaixaListView.as_view(), name='caixa_list'),
    path('caixas/<int:pk>/', CaixaDetailView.as_view(), name='caixa_detail'),
    path('caixa/caixa-total/', CaixaTotalView.as_view(), name='caixa_total'),
    path('caixa/lancamento/<int:pk>/', lancamento_delete_view, name='lancamento_delete'),
    path('caixa/caixa-total/lancamento/<int:pk>/', lancamento_total_delete_view, name='caixa_total_lancamento_delete'),
    path('caixas/kpis/', CaixaKpiCountsView.as_view(), name='caixa_kpis'),

    #cliente
    path('clientes/', ClienteListView.as_view(), name='cliente_list'),
    path('clientes/editar/', cliente_editar_view, name='cliente_edit_form'),
    path('clientes/cliente_create/', ClienteCreateView.as_view(), name='cliente_create'),
    path('clientes/cliente_editar/<int:pk>/', ClienteUpdateView.as_view(), name='cliente_update'),
    path('clientes/cliente_editar_imei_telefone/<int:pk>/', ClienteUpdateImeiTelefoneView.as_view(), name='cliente_update_imei_telefone'),
    
    path('aprovar_analise/<int:id>/', aprovar_analise_credito, name='aprovar_analise'),
    path('reprovar_analise/<int:id>/', reprovar_analise_credito, name='reprovar_analise'),
    path('cancelar_analise/<int:id>/', cancelar_analise_credito, name='cancelar_analise'),
    
    #tipo de pagamento
    path('tipopagamento/', tipoPagamentoViews['list_view'].as_view(), name='tipos_pagamento'),
    path('tipos-pagamento/novo/', tipoPagamentoViews['create_view'].as_view(), name='tipopagamento_create'),
    path('tipos-pagamento/detalhe/<int:pk>/', tipoPagamentoViews['detail_view'].as_view(), name='tipopagamento_detail'),
    path('tipos-pagamento/editar/<int:pk>/', tipoPagamentoViews['update_view'].as_view(), name='tipopagamento_update'),

    #venda
    path('vendas/', VendaListView.as_view(), name='venda_list'),
    path('vendas/editar/<int:pk>/', VendaUpdateView.as_view(), name='venda_update'),
    path('vendas/nova/', VendaCreateView.as_view(), name='venda_create'),
    path('vendas/detail/<int:pk>/', VendaDetailView.as_view(), name='venda_detail'),
    path('vendas/cancelar/<int:id>/', cancelar_venda , name='venda_cancel'),
    path('vendas/trocar/<int:pk>/', VendaTrocarProdutoView.as_view(), name='venda_trocar'),
    
    path('vendas/gerar-venda/<int:cliente_id>/', gerar_venda, name='gerar_venda'),
    
    #Loja
    path('lojas/', LojaListView.as_view(), name='loja_list'),
    path('lojas/nova/', LojaCreateView.as_view(), name='loja_create'),
    path('lojas/editar/<int:pk>/', LojaUpdateView.as_view(), name='loja_update'),
    path('lojas/detalhe/<int:pk>/', LojaDetailView.as_view(), name='loja_detail'),
    path('lojas/replicar/<int:pk>/', replicar_qr_code_codigo_aplicativo, name='loja_replicar'),
    
    
    path('info-products/', product_information, name='info_produto'),
    path('info-payment/', get_payment_method , name='payment_data'),
    
    path('select2/fields/auto.json', ProdutoAutoComplete.as_view(), name='produto-autocomplete'),
    path('produtos/ajax/', get_produtos, name='produtos_ajax'),

    path('vendas/nota/<int:pk>/', VendaPDFView.as_view(), name='venda_pdf'),
    path('caixa/folha/<int:pk>/', FolhaCaixaPDFView.as_view(), name='caixa_pdf'),
    path('caixa/folha-produtos/<int:pk>/', FolhaProdutoPDFView.as_view(), name='caixa_produto_pdf'),
    path('gerar-carne/<int:pk>/<str:tipo>/', folha_carne_view, name='gerar_carne'),
    
    path('vendas/relatorio/', RelatorioVendasView.as_view(), name='venda_relatorio'),
    path('vendas/relatorio/folha/', FolhaRelatorioVendasView.as_view(), name='folha_venda_relatorio'),
    path('vendas/solicitacao/folha/', FolhaRelatorioSolicitacoesView.as_view(), name='folha_solicitacao_relatorio'),
    path('vendas/solicitacao/', RelatorioSolicitacoesView.as_view(), name='form_solicitacao_relatorio'),
    path('venda/contrato/<int:pk>/', contrato_view, name='gerar_contrato'),
    path('produtos-vendidos/', ProdutoVendidoListView.as_view(), name='produto_vendido_list'),
    path('pagamento/<int:pk>/confirmar-quitacao/', ConfirmarQuitacaoView.as_view(), name='confirmar_quitacao'),
    path('gerar_qrcode_pix/<int:loja_id>/', gerar_qrcode_pix, name='gerar_qrcode_pix'),
    
    path(
        'pagamento/<int:pk>/toggle-bloqueio/',
        toggle_bloqueio_pagamento,
        name='toggle_bloqueio_pagamento'
    ),
    path(
        'pagamento/<int:pk>/toggle-desativar/',
        toggle_desativar_pagamento,
        name='toggle_desativar_pagamento'
    ),
    path(
        'pagamento/<int:pk>/toggle-sem-contato/',
        toggle_sem_contato_pagamento,
        name='toggle_sem_contato_pagamento'
    ),
    path(
        'pagamento/<int:pk>/toggle-mais-prazo/',
        toggle_mais_prazo_pagamento,
        name='toggle_mais_prazo_pagamento'
    ),
    path(
        'pagamento/<int:pk>/toggle-devolucao/',
        toggle_devolucao_pagamento,
        name='toggle_devolucao_pagamento'
    ),
    path('pagamento/<int:pk>/toggle-bo/', toggle_bo_pagamento, name='toggle_bo_pagamento'),
    path('pagamento/<int:pk>/toggle-atrasado/', toggle_atrasado_pagamento, name='toggle_atrasado_pagamento'),
    path('pagamento/<int:pk>/toggle-sem-conexao/', toggle_sem_conexao_pagamento, name='toggle_sem_conexao_pagamento'),
    path('pagamento/<int:pk>/toggle-roubo/', toggle_roubo_pagamento, name='toggle_roubo_pagamento'),
    path('pagamento/<int:pk>/toggle-lembrete/', toggle_lembrete_pagamento, name='toggle_lembrete_pagamento'),
    path(
        'pagamento/<int:pk>/toggle-status/<int:status_id>/',
        toggle_status_pagamento,
        name='toggle_status_pagamento'
    ),
    
    path(
        'consultar-pagamentos/',
        ConsultaPagamentosView.as_view(),
        name='consulta_pagamentos'
    ),
    
    path(
        'pagamento/<int:pk>/',
        PagamentoDetailView.as_view(),
        name='pagamento_detail'
    ),
    path('parcela/<int:pk>/informar/', InformarPagamentoView.as_view(), name='parcela_informar'),
    path(
        'pagamento/<int:pk>/informar-todos/',
        InformarTodosPagamentosView.as_view(),
        name='informar_todos_pagamentos'
    ),
    
    path(
        'cliente/<int:pk>/instalar_app/',
        ClienteInstallAppView.as_view(),
        name='cliente_instalar_app'
    ),
    path(
        'cliente/<int:pk>/confirm_installed/',
        ClienteConfirmInstalledView.as_view(),
        name='cliente_confirm_installed'
    ),
    
    path(
        'cliente/<int:pk>/status-app/',
        ClienteStatusAppUpdateView.as_view(),
        name='cliente_status_app_update'
    ),
    
    path(
        'analise/<int:pk>/informar-imei/',
        informar_imei_analise,
        name='informar_imei_analise'
    ),
    
    path(
        'cliente/<int:pk>/analista-confirmar-instalacao/',
        AnalistaConfirmInstalledView.as_view(),
        name='analista_confirm_installed'
    ),

    path('graficos/', GraficoTemplateView.as_view(), name='grafico'),
    path('graficos/relatorio-pdf/', DashboardReportPDFView.as_view(), name='dashboard_report_pdf'),
    
    path(
        'pagamentos/<int:pagamento_pk>/contato/add/',
        ContatoCreateView.as_view(),
        name='pagamento_add_contato'
    ),
    
    path(
      'pagamentos/<int:pagamento_pk>/contato/<int:pk>/edit/',
      ContatoUpdateView.as_view(),
      name='pagamento_edit_contato'
    ),
]
