"""Views do módulo lojas (lojas, repasses e números autenticadores) da API do backoffice."""
from .lojas import LojaDetalheView, LojaLogoView, LojaQrCodeView, LojasView, LojaVendasView, ReplicarQrCodeView
from .numeros import NumerosAutenticadoresViewSet
from .opcoes import OpcoesFormularioView
from .repasses import RepassesAgendadosView, RepassesView, RepasseView

__all__ = [
    'LojaDetalheView',
    'LojaLogoView',
    'LojaQrCodeView',
    'LojasView',
    'LojaVendasView',
    'NumerosAutenticadoresViewSet',
    'OpcoesFormularioView',
    'ReplicarQrCodeView',
    'RepassesAgendadosView',
    'RepassesView',
    'RepasseView',
]
