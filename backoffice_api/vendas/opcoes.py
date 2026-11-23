"""Opções dos formulários de edição da venda na SPA (tipos de pagamento, vendedores, produtos, clientes).

Só leitura; o servidor valida de novo cada escolha no PATCH/edição especial.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q, QuerySet

from produtos.models import Produto
from vendas.forms import PagamentoEdicaoEspecialForm
from vendas.models import TipoPagamento

from .consultas import somente_digitos
from .serializers import mascarar_cpf, nome_do_usuario

#: Desconto (em % do subtotal do item) acima do qual a tela pede autorização de gerente.
LIMITE_DESCONTO_PERCENTUAL = 15
MINIMO_DIGITOS_CPF_CLIENTE = 3


def _produtos_da_loja(venda) -> QuerySet:
    if venda.loja is None:
        return Produto.objects.filter(ativo=True)
    return venda.loja.produtos_permitidos_qs(require_stock=False)


def _vendedores(venda) -> list[dict]:
    """Usuários ativos da loja da venda (usuários e gerentes) + o vendedor atual."""
    filtro = Q(pk=venda.vendedor_id)
    if venda.loja_id:
        filtro |= Q(lojas=venda.loja_id) | Q(lojas_gerenciadas=venda.loja_id)
    usuarios = (
        get_user_model().objects.filter(filtro).filter(Q(is_active=True) | Q(pk=venda.vendedor_id))
        .distinct().order_by('first_name', 'username')
    )
    return [{'id': u.pk, 'nome': nome_do_usuario(u)} for u in usuarios]


def opcoes_de_edicao(venda) -> dict:
    produtos = _produtos_da_loja(venda).select_related('tipo').order_by('nome')
    return {
        'tipos_pagamento': [
            {'id': t.pk, 'nome': t.nome, 'carne': t.carne, 'parcelas': t.parcelas, 'caixa': t.caixa,
             'financeira': t.financeira}
            for t in TipoPagamento.objects.order_by('nome')
        ],
        'vendedores': _vendedores(venda),
        'produtos': [
            {'id': p.pk, 'nome': p.nome, 'codigo': p.codigo, 'is_iphone': p.is_iphone,
             'valor': None if p.valor is None else str(p.valor), 'serializado': bool(p.tipo and p.tipo.numero_serial)}
            for p in produtos
        ],
        'parcelas_edicao_especial': [valor for valor, _ in PagamentoEdicaoEspecialForm.PARCELAS_CHOICES],
        'limite_desconto_percentual': LIMITE_DESCONTO_PERCENTUAL,
    }


def filtrar_clientes(clientes: QuerySet, busca: str) -> QuerySet:
    """Nome (contém) ou CPF (3+ dígitos)."""
    busca = (busca or '').strip()
    if not busca:
        return clientes.order_by('nome')
    filtro = Q(nome__icontains=busca)
    digitos = somente_digitos(busca)
    if len(digitos) >= MINIMO_DIGITOS_CPF_CLIENTE:
        filtro |= Q(cpf__contains=digitos)
    return clientes.filter(filtro).order_by('nome')


def cliente_resumido(cliente) -> dict:
    return {'id': cliente.pk, 'nome': cliente.nome, 'cpf_mascarado': mascarar_cpf(cliente.cpf)}
