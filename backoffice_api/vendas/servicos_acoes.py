"""Troca de produto, cancelamento e autorização de gerente (regras das telas antigas)."""
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from estoque.models import Estoque
from produtos.models import Produto
from vendas.services.erros import ErroDeNegocio

from .regras import garantir_venda_ativa


def _texto_da_troca(user, de_nome, de_imei, para_nome, para_imei, motivo) -> str:
    """Mesmo registro que `vendas/views/vendas.py:VendaTrocarProdutoView` grava na observação."""
    agora = timezone.localtime(timezone.now())
    return (
        f"\n{agora:%d/%m/%Y} {agora:%H:%M} | Troca de produto:\n"
        f"- Usuário: {user.username}\n"
        f"- De: {de_nome} - {de_imei}\n"
        f"- Para: {para_nome} - {para_imei}\n"
        f"- Motivo: {motivo}"
    )


def produtos_para_troca(venda) -> QuerySet:
    """Produtos com estoque disponível na loja da venda (lista da tela de troca)."""
    ids = Estoque.objects.filter(loja=venda.loja, quantidade_disponivel__gt=0).values('produto_id')
    return Produto.objects.filter(pk__in=ids, ativo=True).order_by('nome')


def trocar_produto(venda, dados: dict, user, *, imeis: QuerySet) -> dict:
    """Troca produto e IMEI de um item, marca a venda como trocada e registra na observação.

    `imeis`: IMEIs disponíveis no escopo do usuário. Estoque e IMEI antigo não são
    alterados (como hoje).
    """
    garantir_venda_ativa(venda)
    item = venda.itens_venda.select_related('produto').filter(pk=dados['produto_atual']).first()
    erros = {}
    if item is None:
        erros['produto_atual'] = ['Item não pertence a esta venda.']
    produto = Produto.objects.filter(pk=dados['novo_produto'], ativo=True).first()
    if produto is None:
        erros['novo_produto'] = ['Produto não encontrado ou inativo.']
    imei = imeis.filter(pk=dados['imei']).first()
    if imei is None:
        erros['imei'] = ['IMEI não encontrado ou indisponível.']
    elif produto is not None and imei.produto_id != produto.pk:
        erros['imei'] = ['Este IMEI não é do produto escolhido.']
    if erros:
        raise ValidationError(erros)

    de = {'produto': item.produto_id, 'produto_nome': item.produto.nome, 'imei': item.imei}
    with transaction.atomic():
        item.produto = produto
        item.imei = imei.imei
        item.save(user=user)
        venda.is_trocado = True
        venda.observacao = (venda.observacao or '') + _texto_da_troca(
            user, de['produto_nome'], de['imei'], produto.nome, imei.imei, dados['motivo'],
        )
        venda.save(user=user)
    return {'item': item.pk, 'de': de, 'para': {'produto': produto.pk, 'produto_nome': produto.nome, 'imei': imei.imei}}


def cancelar_venda(venda, user) -> None:
    """Soft delete (`is_deleted`), como a tela; o IMEI não é restaurado."""
    if venda.is_deleted:
        raise ErroDeNegocio('Esta venda já está cancelada.')
    venda.is_deleted = True
    venda.save(user=user)


class AutorizacaoNegada(Exception):
    """Falha da autorização de gerente; `motivo` vai para a auditoria."""

    def __init__(self, mensagem: str, motivo: str):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.motivo = motivo


class AutorizacaoBloqueada(Exception):
    """Muitas tentativas erradas para o usuário informado (django-axes)."""


def autorizar_gerente(request, usuario: str, senha: str, loja):
    """Confere usuário e senha e se ele é gerente da loja (regra de `accounts.views.get_autorizacao_user`).

    Usa `authenticate` para contar as falhas no bloqueio por tentativas; não cria sessão.
    """
    django_request = getattr(request, '_request', request)
    gerente = authenticate(django_request, username=usuario, password=senha)
    if getattr(django_request, 'axes_locked_out', False):
        raise AutorizacaoBloqueada
    if gerente is None:
        raise AutorizacaoNegada('Autorização negada: usuário ou senha incorretos.', 'credenciais')
    if not loja.gerentes.filter(pk=gerente.pk).exists():
        raise AutorizacaoNegada('Autorização negada: o usuário não é gerente desta loja.', 'nao_gerente')
    return gerente
