import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from vendas.models import AnaliseCreditoCliente, Cliente, PreAnaliseRapida
from django.contrib.auth import get_user_model
from notifications.signals import notify
from notificacao.utils import enviar_ws_para_usuario
from estoque.models import EntradaEstoque

User = get_user_model()

logger = logging.getLogger(__name__)


def _ws_seguro(**kwargs):
    """Envia notificação WS de forma best-effort.

    Uma indisponibilidade do canal (ex.: Redis offline) NÃO deve derrubar o
    request nem a transação que originou a notificação.
    """
    try:
        enviar_ws_para_usuario(**kwargs)
    except Exception:  # noqa: BLE001 — notificação em tempo real é best-effort
        logger.warning("Falha ao enviar notificação WebSocket (ignorada).", exc_info=True)

@receiver(pre_save, sender=AnaliseCreditoCliente)
def status_anterior(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance.status_anterior = AnaliseCreditoCliente.objects.get(pk=instance.pk).status
        except AnaliseCreditoCliente.DoesNotExist:
            instance.status_anterior = None


@receiver(post_save, sender=AnaliseCreditoCliente)
def notificar_status_analise_credito(sender, instance, created, **kwargs):
    cliente_nome = instance.cliente.nome if instance.cliente else "Cliente"
    if created:
        verb = f'Nova análise de crédito criada para o cliente {cliente_nome.capitalize()}.'
        imei_info = f'Imei {instance.imei.imei}' if instance.imei else 'IMEI não informado'
        description = f'{imei_info} da loja {instance.loja.nome.capitalize()}.'
        
        # Admins + analista que criou
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=instance.criado_por_id)
        )
        if instance.criado_por:
            usuarios_para_notificar.append(instance.criado_por)
        
        for user in usuarios_para_notificar:
            notify.send(
                instance,
                recipient=user,
                verb=verb,
                description=description,
                target=instance.cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=instance,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=instance.cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                    # Dispara o modal central do ANALISTA/ADMIN no front Django
                    event='proposta_criada',
                )

    if instance.status_aplicativo == 'C':
        verb = f'Instalação do cliente {cliente_nome.capitalize()} está aguardando confirmação.'
        imei_info = f'Imei {instance.imei.imei}' if instance.imei else 'IMEI não informado'
        description = f'{imei_info} da loja {instance.loja.nome.capitalize()}.'

        # Admins + analista que criou
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=instance.criado_por_id)
        )

        if instance.criado_por:
            usuarios_para_notificar.append(instance.criado_por)

        for user in usuarios_para_notificar:
            notify.send(
                instance,
                recipient=user,
                verb=verb,
                description=description,
                target=instance.cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=instance,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=instance.cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )

    if not hasattr(instance, 'status_anterior'):
        instance.status_anterior = instance.status
        
    if (instance.status != instance.status_anterior) and not created:
        if instance.status == 'A':
            verb = f'Análise de crédito do cliente {cliente_nome.capitalize()} foi aprovada.'
            evento = 'proposta_aceita'
        elif instance.status == 'R':
            verb = f'Análise de crédito do cliente {cliente_nome.capitalize()} foi rejeitada.'
            evento = 'proposta_negada'
        elif instance.status == 'C':
            verb = f'Análise de crédito do cliente {cliente_nome.capitalize()} foi cancelada.'
            evento = 'proposta_cancelada'
        else:
            return

        imei_info = f'Imei {instance.imei.imei}' if instance.imei else 'IMEI não informado'
        description = f'{imei_info} da loja {instance.loja.nome.capitalize()}.'

        # Somente o Criador (vendedor)
        usuarios_para_notificar = [instance.criado_por] if instance.criado_por else []

        for user in usuarios_para_notificar:
            notify.send(
                instance,
                recipient=user,
                verb=verb,
                description=description,
                target=instance.cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=instance,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=instance.cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                    # Dispara o modal central do VENDEDOR no front React
                    event=evento,
                )
                
                
#     if created:
#         verb = f'Nova entrada de estoque registrada.'
#         description = f'Entrada Estoque'

#         # Notificar administradores e analistas
#         usuarios_para_notificar = list(
#             User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=instance.criado_por_id)
#         )

#         if instance.criado_por:
#             usuarios_para_notificar.append(instance.criado_por)

#         for user in usuarios_para_notificar:
#             notify.send(
#                 instance,
#                 recipient=user,
#                 verb=verb, 
#                 description=description,
#                 target=instance,
#             )

#             # WebSocket
#             ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
#             if ultima_notificacao:
#                 enviar_ws_para_usuario(
#                     usuario=user,
#                     instance=instance,
#                     notification_id=ultima_notificacao.id,
#                     verb=verb,
#                     description=description,
#                     target_url=instance.get_absolute_url(),
#                     type_notification='entrada_estoque',
#                 )


                
@receiver(pre_save, sender=PreAnaliseRapida)
def pre_analise_status_anterior(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._status_anterior = PreAnaliseRapida.objects.get(pk=instance.pk).status
        except PreAnaliseRapida.DoesNotExist:
            instance._status_anterior = None
    else:
        instance._status_anterior = None


@receiver(post_save, sender=PreAnaliseRapida)
def notificar_pre_analise_rapida(sender, instance, created, **kwargs):
    loja_nome = instance.loja.nome.capitalize() if instance.loja else 'sua loja'

    # 1) Criação → notifica ANALISTA/ADMIN (modal central no backoffice Django)
    if created:
        verb = f'Nova análise rápida de {instance.nome_completo.title()}.'
        description = f'CPF {instance.cpf} — loja {loja_nome}.'

        destinatarios = list(
            User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=instance.criado_por_id)
        )
        for user in destinatarios:
            notify.send(instance, recipient=user, verb=verb, description=description, target=instance)
            ultima = user.notifications.unread().order_by('-timestamp').first()
            if ultima:
                _ws_seguro(
                    usuario=user,
                    instance=instance,
                    notification_id=ultima.id,
                    verb=verb,
                    description=description,
                    target_url=instance.get_absolute_url(),
                    type_notification='pre_analise_rapida',
                    # Dispara o modal central do ANALISTA/ADMIN no front Django
                    event='pre_analise_criada',
                )
        return

    # 2) Decisão (pré-aprovada/reprovada) → notifica vendedor + gerentes (modal React)
    status_anterior = getattr(instance, '_status_anterior', None)
    if instance.status != status_anterior and instance.status in ('A', 'R'):
        if instance.status == 'A':
            verb = f'Análise rápida de {instance.nome_completo.title()} foi pré-aprovada.'
            evento = 'pre_analise_aprovada'
        else:
            verb = f'Análise rápida de {instance.nome_completo.title()} foi reprovada.'
            evento = 'pre_analise_reprovada'
        description = f'CPF {instance.cpf} — loja {loja_nome}.'

        destinatarios = []
        if instance.criado_por:
            destinatarios.append(instance.criado_por)
        if instance.loja_id:
            destinatarios.extend(instance.loja.gerentes.all())
        # remove duplicados preservando ordem
        vistos = set()
        destinatarios = [u for u in destinatarios if u and not (u.id in vistos or vistos.add(u.id))]

        for user in destinatarios:
            notify.send(instance, recipient=user, verb=verb, description=description, target=instance)
            ultima = user.notifications.unread().order_by('-timestamp').first()
            if ultima:
                _ws_seguro(
                    usuario=user,
                    instance=instance,
                    notification_id=ultima.id,
                    verb=verb,
                    description=description,
                    # Rota do SPA React (lista de análises rápidas)
                    target_url='/app/analise-rapida',
                    type_notification='pre_analise_rapida',
                    # Dispara o modal central do VENDEDOR/GERENTE no front React
                    event=evento,
                )


@receiver(post_save, sender=EntradaEstoque)
def notificar_administradores_entrada(sender, instance, created, **kwargs):
    if created:
        loja_nome = instance.loja.nome.capitalize()
        criado_por = instance.criado_por.get_full_name()
        criado_por = criado_por.capitalize() if criado_por else instance.criado_por.username.capitalize()
        admins = User.objects.filter(groups__name__icontains="ADMINISTRADOR").exclude(id=instance.criado_por_id)
        for admin in admins:
            notificacoes = notify.send(
                instance,
                recipient=admin,
                verb=f'Nova entrada de estoque registrada na {loja_nome.capitalize()} por {criado_por.capitalize()}',
                description=f'Entrada {instance.numero_nota}',
                target=instance,
            )

            # Extrai a notificação criada
            notification = admin.notifications.unread().order_by('-timestamp').first()

            if notification:
                enviar_ws_para_usuario(admin, instance, notification.id, 
                verb=f'Nova entrada de estoque registrada na {loja_nome.capitalize()} por {criado_por.capitalize()}', 
                description=f'Entrada {instance.numero_nota}',
                target_url=instance.get_absolute_url(),
                type_notification='entrada_estoque',
                )