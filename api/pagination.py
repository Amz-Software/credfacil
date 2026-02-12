from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class SolicitacaoPagination(PageNumberPagination):
    page_size = 10
