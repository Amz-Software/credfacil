"""View base com a loja da sessão (usada também por financeiro e produtos)."""
import logging

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.views.generic import View

from vendas.models import Loja


logger = logging.getLogger(__name__)


class BaseView(View):
    def get_loja(self):
        loja_id = self.request.session.get('loja_id')
        if loja_id:
            return get_object_or_404(Loja, id=loja_id)
        return None

    def get_queryset(self):
        loja = self.get_loja()
        if loja:
            return super().get_queryset().filter(loja=loja)
        
        if not loja:
            raise Http404("Loja não encontrada para o usuário.")

        return super().get_queryset()
