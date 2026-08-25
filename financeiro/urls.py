from django.urls import path
from .views import *
from utils import gerador_views


app_name = 'financeiro'

gasto_fixo_views = gerador_views.generate_views(GastoFixo, GastoFixoForm, 10, template_dir='gasto_fixo')

urlpatterns = [
    path('financeiro/caixa-mensal', CaixaMensalListView.as_view(), name='caixa_mensal_list'),
    path('financeiro/caixa-mensal/novo', caixa_mensal_create , name='caixa_mensal_create'),
    path('financeiro/caixa-mensal/<int:pk>', CaixaMensalDetailView.as_view(), name='caixa_mensal_update'),
    path('financeiro/caixa-mensal/<int:pk>/fechar', fechar_caixa_mensal, name='caixa_mensal_close'),
    path('financeiro/caixa-mensal/<int:pk>/reabrir', reabrir_caixa_mensal, name='caixa_mensal_reopen'),

    path('financeiro/contas-a-receber', ContasAReceberListView.as_view(), name='contas_a_receber_list'),
    path('financeiro/contas-a-receber/<int:pk>', ContasAReceberDetailView.as_view(), name='contas_a_receber_update'),
    path('financeiro/contas-a-receber/<int:pk>/gerar-bo/', GerarNotificacaoBoView.as_view(), name='notificacao_bo_preview'),
    path('financeiro/contas-a-receber/<int:pk>/gerar-bo/pdf/', GerarNotificacaoBoPdfView.as_view(), name='notificacao_bo_pdf'),

    path('gastofixo/', gasto_fixo_views['list_view'].as_view(), name='gasto_fixo_list'),
    path('gasto-fixo/novo', gasto_fixo_views['create_view'].as_view(), name='gasto_fixo_create'),
    path('gasto-fixo/<int:pk>/detalhe', gasto_fixo_views['detail_view'].as_view(), name='gasto_fixo_detail'),
    path('gasto-fixo/<int:pk>', gasto_fixo_views['update_view'].as_view(), name='gasto_fixo_update'),

    path('relatorio/saidas', RelatorioSaidaView.as_view(), name='relatorio_saidas'),
    path('relatorio/folha-saida', FolhaRelatorioSaidaView.as_view(), name='relatorio_folha_saida'),
    
    path('repasse/criar/', RepasseCreateView.as_view(), name='repasse_create'),
    path('repasse/<int:pk>/editar/', RepasseUpdateView.as_view(), name='repasse_edit'),

    path('relatorio/contas-a-receber', RelatorioContasAReceberView.as_view(), name='relatorio_contas_a_receber'),
    path('relatorio/contas-a-pagar/folha', FolhaRelatorioContasAReceberView.as_view(), name='relatorio_folha_contas_a_receber'),
    path('relatorio/contas-a-receber/avancado', RelatorioContasAReceberAvancadoView.as_view(), name='relatorio_contas_a_receber_avancado'),
    path('relatorio/contas-a-receber/folha-avancado', FolhaRelatorioContasAReceberAvancadoView.as_view(), name='relatorio_folha_contas_a_receber_avancado'),

    path('relatorio/parcelas', RelatorioParcelasView.as_view(), name='relatorio_parcelas'),
    path('relatorio/parcelas/excel', RelatorioParcelasExcelView.as_view(), name='relatorio_parcelas_excel'),

]
