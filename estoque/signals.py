from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.utils import timezone
from notificacao.utils import enviar_ws_para_usuario
from .models import Estoque, EntradaEstoque, ProdutoEntrada, EstoqueImei
from vendas.models import ProdutoVenda, Venda
from django.db import transaction
from django.contrib.auth.models import Group
from notifications.signals import notify
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(pre_save, sender=ProdutoEntrada)
def salvar_quantidade_antiga(instance, **kwargs):
    if instance.pk:
        instance._quantidade_antiga = ProdutoEntrada.objects.get(pk=instance.pk).quantidade
    else:
        instance._quantidade_antiga = 0


@receiver(post_save, sender=ProdutoEntrada)
def atualizar_estoque_entrada(instance, created, **kwargs):
    if created:
        # Verifica se o estoque já existe para o produto e loja
        estoque = Estoque.objects.filter(produto=instance.produto, loja=instance.loja).first()
        if not estoque:
            estoque = Estoque.objects.create(produto=instance.produto, loja=instance.loja)
        estoque.adicionar_estoque(instance.quantidade)
    else:
        estoque = Estoque.objects.filter(produto=instance.produto, loja=instance.loja).first()
        quantidade_antiga = instance._quantidade_antiga
        quantidade_nova = instance.quantidade
        
        if quantidade_nova > quantidade_antiga:
            estoque.adicionar_estoque(quantidade_nova - quantidade_antiga)
        elif quantidade_nova < quantidade_antiga:
            estoque.remover_estoque(quantidade_antiga - quantidade_nova)


@receiver(post_delete, sender=ProdutoEntrada)
def atualizar_estoque_deletar_entrada(sender, instance, **kwargs):
    estoque = Estoque.objects.filter(produto=instance.produto, loja=instance.loja).first()
    estoque.remover_estoque(instance.quantidade)

@receiver(post_delete, sender=ProdutoVenda)
def atualizar_estoque_deletar_venda(sender, instance, **kwargs):
    # Validações e atualizações de estoque removidas conforme solicitado
    # Esta função agora não executa nenhuma validação ou atualização de estoque
    pass

@receiver(post_save, sender=Venda)
def atualizar_estoque_apos_cancelar_venda(sender, instance, **kwargs):
    """
    Atualiza o estoque quando uma venda é cancelada (is_deleted=True).
    Validações e atualizações de estoque removidas conforme solicitado.
    """
    # Função desabilitada - não executa mais validações ou atualizações de estoque
    pass

@receiver(pre_save, sender=ProdutoVenda)
def salvar_quantidade_antiga(instance, **kwargs):
    if instance.pk:
        try:
            produto_venda_antigo = ProdutoVenda.objects.get(pk=instance.pk)
            instance._quantidade_antiga = produto_venda_antigo.quantidade
            instance._produto_antigo = produto_venda_antigo
        except ProdutoVenda.DoesNotExist:
            instance._quantidade_antiga = 0
            instance._produto_antigo = None
    else:
        instance._quantidade_antiga = 0
        instance._produto_antigo = None

@receiver(post_save, sender=ProdutoVenda)
def atualizar_estoque_apos_editar_venda(sender, created, instance, **kwargs):
    # Validações e atualizações de estoque removidas conforme solicitado
    # Esta função agora não executa nenhuma validação ou atualização de estoque
    pass
