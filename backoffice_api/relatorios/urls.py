"""Rotas do módulo relatorios da API do backoffice."""
from django.urls import path

from .definicoes import RELATORIOS
from .views import CatalogoRelatoriosView, RelatorioParcelasExcelView, views_do_relatorio

urlpatterns: list = [
    path('catalogo/', CatalogoRelatoriosView.as_view(), name='catalogo'),
    path('parcelas/excel/', RelatorioParcelasExcelView.as_view(), name='parcelas_excel'),
]

for _definicao in RELATORIOS.values():
    _previa, _pdf = views_do_relatorio(_definicao)
    urlpatterns += [
        path(f'{_definicao.id}/previa/', _previa.as_view(), name=f'{_definicao.id}_previa'),
        path(f'{_definicao.id}/pdf/', _pdf.as_view(), name=f'{_definicao.id}_pdf'),
    ]
