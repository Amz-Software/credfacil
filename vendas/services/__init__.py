"""Regras de negócio de vendas compartilhadas pelo backoffice (templates) e pela API.

Cada função tem uma única implementação aqui; as views só traduzem o resultado
(ou o `ErroDeNegocio`) para mensagens + redirect (Django) ou `Response` (DRF).
"""
from .erros import ErroDeNegocio

__all__ = ['ErroDeNegocio']
