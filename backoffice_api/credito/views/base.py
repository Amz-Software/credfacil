"""Peças comuns das views do módulo de crédito."""
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.negotiation import BaseContentNegotiation

TAG = 'bo-credito'


class MetodoAntesDaPermissaoMixin:
    """Responde 405 para método sem rota antes de conferir permissões.

    Sem isto, um GET numa ação que só aceita POST cairia em `PermissoesDeclaradas`
    (a chave seria o método, não declarado) e viraria 403.
    """

    def initial(self, request, *args, **kwargs):
        metodo = request.method.lower()
        if metodo != 'options' and (metodo not in self.http_method_names or not hasattr(self, metodo)):
            raise MethodNotAllowed(request.method)
        super().initial(request, *args, **kwargs)


class NegociacaoSemAccept(BaseContentNegotiation):
    """Arquivos e PDFs: ignora o `Accept` (o navegador pede image/* ou application/pdf).

    O primeiro renderizador (JSON) continua sendo usado nas respostas de erro.
    """

    def select_parser(self, request, parsers):
        return parsers[0] if parsers else None

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type
