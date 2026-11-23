"""Views do catálogo (produtos, tipos, marcas e parcelamentos)."""
from .marcas import MarcaViewSet
from .parcelamentos import ParcelamentoViewSet
from .produtos import ProdutoRelatorioPDFView, ProdutoViewSet
from .tipos import TipoProdutoViewSet

__all__ = [
    'MarcaViewSet',
    'ParcelamentoViewSet',
    'ProdutoRelatorioPDFView',
    'ProdutoViewSet',
    'TipoProdutoViewSet',
]
