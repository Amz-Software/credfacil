from django.urls import path
from .views import *


app_name = 'financeiro'

urlpatterns = [
    path('financeiro/contas-a-receber', ContasAReceberListView.as_view(), name='contas_a_receber_list'),
    path('financeiro/contas-a-receber/<int:pk>', ContasAReceberDetailView.as_view(), name='contas_a_receber_update'),
    path('financeiro/contas-a-receber/<int:pk>/gerar-bo/', GerarNotificacaoBoView.as_view(), name='notificacao_bo_preview'),
    path(
        'financeiro/contas-a-receber/<int:pk>/parcela/<int:parcela_pk>/comprovante/',
        ComprovanteParcelaUploadView.as_view(),
        name='comprovante_parcela_upload',
    ),
    path(
        'financeiro/contas-a-receber/<int:pk>/parcela/<int:parcela_pk>/comprovante/<int:comprovante_pk>/arquivo/',
        ComprovanteParcelaDownloadView.as_view(),
        name='comprovante_parcela_download',
    ),
    path(
        'financeiro/contas-a-receber/<int:pk>/parcela/<int:parcela_pk>/comprovante/<int:comprovante_pk>/remover/',
        ComprovanteParcelaDeleteView.as_view(),
        name='comprovante_parcela_delete',
    ),
    path('financeiro/contas-a-receber/<int:pk>/gerar-bo/pdf/', GerarNotificacaoBoPdfView.as_view(), name='notificacao_bo_pdf'),

    
    path('repasse/criar/', RepasseCreateView.as_view(), name='repasse_create'),
    path('repasse/<int:pk>/editar/', RepasseUpdateView.as_view(), name='repasse_edit'),

    path('relatorio/contas-a-receber', RelatorioContasAReceberView.as_view(), name='relatorio_contas_a_receber'),
    path('relatorio/contas-a-pagar/folha', FolhaRelatorioContasAReceberView.as_view(), name='relatorio_folha_contas_a_receber'),
    path('relatorio/contas-a-receber/avancado', RelatorioContasAReceberAvancadoView.as_view(), name='relatorio_contas_a_receber_avancado'),
    path('relatorio/contas-a-receber/folha-avancado', FolhaRelatorioContasAReceberAvancadoView.as_view(), name='relatorio_folha_contas_a_receber_avancado'),

    path('relatorio/parcelas', RelatorioParcelasView.as_view(), name='relatorio_parcelas'),
    path('relatorio/parcelas/excel', RelatorioParcelasExcelView.as_view(), name='relatorio_parcelas_excel'),

]
