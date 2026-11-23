"""Paginação padrão da API do backoffice."""
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

TAMANHO_PADRAO = 25
TAMANHO_MAXIMO = 100


class PaginacaoBackoffice(PageNumberPagination):
    """Responde {count, page, page_size, total_pages, results}."""

    page_size = TAMANHO_PADRAO
    page_size_query_param = 'page_size'
    max_page_size = TAMANHO_MAXIMO

    def get_paginated_response(self, data) -> Response:
        return Response({
            'count': self.page.paginator.count,
            'page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'total_pages': self.page.paginator.num_pages,
            'results': data,
        })

    def get_paginated_response_schema(self, schema: dict) -> dict:
        return {
            'type': 'object',
            'required': ['count', 'page', 'page_size', 'total_pages', 'results'],
            'properties': {
                'count': {'type': 'integer'},
                'page': {'type': 'integer'},
                'page_size': {'type': 'integer'},
                'total_pages': {'type': 'integer'},
                'results': schema,
            },
        }
