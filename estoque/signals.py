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
    estoque = Estoque.objects.filter(produto__nome=instance.produto.nome, loja=instance.loja)
    if not estoque.exists():
        raise ValidationError(f"Estoque não encontrado para o produto {instance.produto.nome} na loja {instance.loja}.")
    estoque = estoque.first()
    estoque.adicionar_estoque(instance.quantidade)

@receiver(post_save, sender=Venda)
def atualizar_estoque_apos_cancelar_venda(sender, instance, **kwargs):
    """
    Atualiza o estoque quando uma venda é cancelada (is_deleted=True).
    """
    if instance.is_deleted:  # Apenas processa se a venda foi cancelada
        # Recupera todos os itens da venda
        venda_items = ProdutoVenda.objects.filter(venda=instance)

        for item in venda_items:
            # Atualiza o estoque do IMEI, se existir
            if item.imei:
                estoque_imei = EstoqueImei.objects.filter(imei=item.imei, loja=item.loja).first()
                if estoque_imei:  # Apenas processa se encontrar algo
                    estoque_imei.vendido = False
                    estoque_imei.data_venda = None
                    estoque_imei.loja = None
                    estoque_imei.save()
                else:
                    raise Exception(f"Estoque IMEI não encontrado para o IMEI {item.imei}.")

            # Atualiza o estoque geral do produto
            try:
                estoque = Estoque.objects.get(produto=item.produto, loja=item.loja)
                estoque.adicionar_estoque(item.quantidade)
                estoque.save()
            except Estoque.DoesNotExist:
                raise Exception(f"Estoque não encontrado para o produto {item.produto.nome} na loja {item.loja}.")

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
    with transaction.atomic():
        if created:
            # Quando ProdutoVenda é criado pela primeira vez, marca o IMEI como vendido
            if instance.imei:
                estoque_imei = EstoqueImei.objects.filter(imei=instance.imei, loja=instance.loja).select_for_update().first()
                if estoque_imei:
                    estoque_imei.vendido = True
                    estoque_imei.data_venda = timezone.now()
                    estoque_imei.loja = instance.loja
                    estoque_imei.save()
                else:
                    raise Exception(f"Estoque IMEI não encontrado para o IMEI {instance.imei}.")
        else:
            # Atualização de IMEI se houver mudança
            if getattr(instance._produto_antigo, 'imei', None) and instance.imei and instance._produto_antigo.imei != instance.imei:
                estoque_imei_antigo = EstoqueImei.objects.filter(imei=instance._produto_antigo.imei, loja=instance.loja).select_for_update().first()
                if estoque_imei_antigo:
                    estoque_imei_antigo.vendido = False
                    estoque_imei_antigo.data_venda = None
                    estoque_imei_antigo.loja = None
                    estoque_imei_antigo.save()
                else:
                    raise Exception(f"Estoque IMEI não encontrado para o IMEI {instance._produto_antigo.imei}.")
                
                estoque_imei_novo = EstoqueImei.objects.filter(imei=instance.imei, loja=instance.loja).select_for_update().first()
                if estoque_imei_novo:
                    estoque_imei_novo.vendido = True
                    estoque_imei_novo.data_venda = timezone.now()
                    estoque_imei_novo.loja = instance.loja
                    estoque_imei_novo.save()
                else:
                    raise Exception(f"Estoque IMEI não encontrado para o IMEI {instance.imei}.")

            try:
                estoque_novo = Estoque.objects.select_for_update().get(produto=instance.produto, loja=instance.loja)
                quantidade_antiga = instance._quantidade_antiga
                quantidade_nova = instance.quantidade
                
                print('ESTOQUE NOVO', estoque_novo)
                print('QUANTIDADE ANTIGA', quantidade_antiga)
                print('QUANTIDADE NOVA', quantidade_nova)

                if instance._produto_antigo and instance._produto_antigo.produto != instance.produto:
                    if getattr(instance._produto_antigo, 'imei', None):
                        estoque_imei_antigo = EstoqueImei.objects.filter(imei=instance._produto_antigo.imei, loja=instance.loja).select_for_update().first()
                        if estoque_imei_antigo:
                            estoque_imei_antigo.vendido = False
                            estoque_imei_antigo.data_venda = None
                            estoque_imei_antigo.loja = None
                            estoque_imei_antigo.save()
                        else:
                            raise Exception(f"Estoque IMEI não encontrado para o IMEI {instance._produto_antigo.imei}.")
                    
                    estoque_antigo = Estoque.objects.select_for_update().get(produto=instance._produto_antigo.produto, loja=instance.loja)
                    estoque_antigo.quantidade_disponivel = estoque_antigo.quantidade_disponivel + quantidade_antiga
                    estoque_antigo.save()
                    
                    estoque_novo.quantidade_disponivel = estoque_novo.quantidade_disponivel - quantidade_nova
                else:
                    if quantidade_nova > quantidade_antiga:
                        # estoque_novo.quantidade_disponivel = estoque_novo.quantidade_disponivel - (quantidade_nova - quantidade_antiga)
                        diferenca = quantidade_nova - quantidade_antiga
                        estoque_novo.remover_estoque(diferenca)
                    elif quantidade_nova < quantidade_antiga:
                        # estoque_novo.quantidade_disponivel = estoque_novo.quantidade_disponivel + (quantidade_antiga - quantidade_nova)
                        diferenca = quantidade_antiga - quantidade_nova
                        estoque_novo.adicionar_estoque(diferenca)
                
                estoque_novo.save()
            except Estoque.DoesNotExist:
                raise Exception(f"Estoque não encontrado para o produto {instance.produto.nome} na loja {instance.loja}.")
            
            
