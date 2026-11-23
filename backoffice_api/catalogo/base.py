"""Base das views do catálogo na API do backoffice.

- `RecusaMetodoMixin`: método sem rota (ex.: GET numa ação só de POST) responde 405
  antes da checagem de permissões; sem ele, `PermissoesDeclaradas` responderia 403
  para quem não é superusuário.
- `lojas_para_filtro`/`loja_escolhida`: leitura do cabeçalho `X-Loja` já cruzado com
  o escopo do servidor (ver `backoffice_api.nucleo.escopo`).
"""
from django.db.models import QuerySet
from rest_framework.exceptions import MethodNotAllowed

from backoffice_api.nucleo.escopo import CABECALHO_LOJA, TODAS, escopo_lojas, tem_acesso_global
from backoffice_api.nucleo.views import BackofficeAPIView, BackofficeViewSet
from vendas.models import Loja


class RecusaMetodoMixin:
    """405 no contrato para método não mapeado, antes de autenticação e permissões."""

    def initial(self, request, *args, **kwargs):
        if request.method.upper() not in self.allowed_methods:
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)


class CatalogoViewSet(RecusaMetodoMixin, BackofficeViewSet):
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    lookup_value_regex = r'\d+'


class CatalogoAPIView(RecusaMetodoMixin, BackofficeAPIView):
    pass


def _valor_x_loja(request) -> str:
    return (request.headers.get(CABECALHO_LOJA) or '').strip().lower()


def lojas_para_filtro(view) -> QuerySet | None:
    """Lojas que restringem a consulta; None quando não há restrição.

    Sem restrição = acesso global (superusuário/`can_view_all_stores`) sem loja
    escolhida em `X-Loja`. Caso contrário, as lojas efetivas da requisição.
    """
    request = view.request
    if _valor_x_loja(request) in ('', TODAS) and tem_acesso_global(request.user, view.permissao_global_lojas):
        return None
    return view.lojas()


def loja_escolhida(view) -> Loja | None:
    """A loja pedida em `X-Loja` (já conferida com o escopo) ou None para vazio/"todas"."""
    if _valor_x_loja(view.request) in ('', TODAS):
        return None
    return view.lojas().first()


def ids_escopo_de_escrita(view) -> set[int] | None:
    """Lojas que quem edita pode vincular; None = todas (acesso global)."""
    user = view.request.user
    if tem_acesso_global(user, view.permissao_global_lojas):
        return None
    return set(escopo_lojas(user, view.permissao_global_lojas).values_list('pk', flat=True))
