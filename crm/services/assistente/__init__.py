"""Assistente de IA do WhatsApp (Claude): conversa em linguagem natural no lugar do menu.

Entrada única: `atender(conversa)`. Liga com ConfiguracaoCRM.assistente_ativo + ANTHROPIC_API_KEY.
"""
from crm.services.assistente.ia import disponivel, liberado_para
from crm.services.assistente.motor import FalhaAssistente, atender

__all__ = ['FalhaAssistente', 'atender', 'disponivel', 'liberado_para']
