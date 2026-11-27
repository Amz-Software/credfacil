"""Views do módulo financeiro (contas a receber) da API do backoffice."""
from .contas import (
    ContaAReceberDetalheView,
    ContasAReceberListaView,
    QuitarView,
    SituacoesView,
    StatusPagamentoListaView,
)
from .contato_crm import ContatoCrmView, NotaCrmView, TentativaCrmView
from .contatos_bo import BoPdfView, BoPreviaView, ContatoCriarView, ContatoEditarView
from .parcelas import (
    AdicionarParcelasView,
    ComprovanteArquivoView,
    ComprovanteUploadView,
    ComprovanteView,
    ParcelaView,
)

__all__ = [
    'AdicionarParcelasView',
    'BoPdfView',
    'BoPreviaView',
    'ComprovanteArquivoView',
    'ComprovanteUploadView',
    'ComprovanteView',
    'ContaAReceberDetalheView',
    'ContasAReceberListaView',
    'ContatoCrmView',
    'ContatoCriarView',
    'ContatoEditarView',
    'NotaCrmView',
    'ParcelaView',
    'QuitarView',
    'SituacoesView',
    'StatusPagamentoListaView',
    'TentativaCrmView',
]
