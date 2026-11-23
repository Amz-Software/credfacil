"""Páginas públicas do CRM (sem login): política de privacidade exigida pela Meta."""
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from crm.models import ConfiguracaoCRM


@require_GET
def politica_privacidade(request: HttpRequest) -> HttpResponse:
    return render(request, 'crm/privacidade.html', {'config': ConfiguracaoCRM.obter()})
