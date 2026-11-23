"""Base das views da administração na API do backoffice.

`RecusaMetodoMixin`: método sem rota (ex.: GET numa ação só de POST) responde 405
antes da checagem de permissões; sem ele, `PermissoesDeclaradas` responderia 403.
"""
from django.db.models import QuerySet
from rest_framework.exceptions import MethodNotAllowed

from backoffice_api.nucleo.escopo import CABECALHO_LOJA, TODAS, escopo_lojas, tem_acesso_global
from backoffice_api.nucleo.views import BackofficeAPIView, BackofficeViewSet


class RecusaMetodoMixin:
    def initial(self, request, *args, **kwargs):
        if request.method.upper() not in self.allowed_methods:
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)


class AdministracaoViewSet(RecusaMetodoMixin, BackofficeViewSet):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    lookup_value_regex = r'\d+'


class AdministracaoAPIView(RecusaMetodoMixin, BackofficeAPIView):
    pass


def lojas_para_filtro(view) -> QuerySet | None:
    """Lojas que restringem a consulta; None = acesso global sem loja escolhida em `X-Loja`."""
    request = view.request
    valor = (request.headers.get(CABECALHO_LOJA) or '').strip().lower()
    if valor in ('', TODAS) and tem_acesso_global(request.user, view.permissao_global_lojas):
        return None
    return view.lojas()


def ids_escopo_de_escrita(user) -> set[int] | None:
    """Lojas que `user` pode vincular a alguém; None = todas (acesso global)."""
    if tem_acesso_global(user):
        return None
    return set(escopo_lojas(user).values_list('pk', flat=True))
