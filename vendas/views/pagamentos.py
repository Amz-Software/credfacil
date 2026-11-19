"""Situações do pagamento (bloqueio, desativação, roubo...) e confirmação de quitação."""
from decimal import Decimal
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View

from vendas.models import Pagamento, StatusPagamento


logger = logging.getLogger(__name__)


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_bloqueio_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.bloqueado = not pagamento.bloqueado
    pagamento.save(update_fields=['bloqueado'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_desativar_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.desativado = not pagamento.desativado
    pagamento.save(update_fields=['desativado'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_sem_contato_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.sem_contato = not pagamento.sem_contato
    pagamento.save(update_fields=['sem_contato'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_mais_prazo_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.mais_prazo = not pagamento.mais_prazo
    pagamento.save(update_fields=['mais_prazo'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_devolucao_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.devolucao = not pagamento.devolucao
    pagamento.save(update_fields=['devolucao'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_bo_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.bo = not pagamento.bo
    pagamento.save(update_fields=['bo'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_atrasado_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.flag_atrasado = not pagamento.flag_atrasado
    pagamento.save(update_fields=['flag_atrasado'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_sem_conexao_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.sem_conexao = not pagamento.sem_conexao
    pagamento.save(update_fields=['sem_conexao'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_roubo_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.roubo = not pagamento.roubo
    pagamento.save(update_fields=['roubo'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_lembrete_pagamento(request, pk):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    pagamento.lembrete = not pagamento.lembrete
    pagamento.save(update_fields=['lembrete'])
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


@login_required
@permission_required('vendas.change_pagamento', raise_exception=True)
def toggle_status_pagamento(request, pk, status_id):
    pagamento = get_object_or_404(Pagamento, pk=pk)
    status = get_object_or_404(StatusPagamento, pk=status_id)
    if pagamento.statuses.filter(pk=status.pk).exists():
        pagamento.statuses.remove(status)
        messages.info(request, f"Status '{status.nome}' removido.")
    else:
        pagamento.statuses.add(status)
        messages.success(request, f"Status '{status.nome}' adicionado.")
    return redirect(reverse('financeiro:contas_a_receber_update', args=[pagamento.pk]))


class ConfirmarQuitacaoView(PermissionRequiredMixin, View):
    """
    View para o ANALISTA. Confirma a quitação, ajusta os valores
    das parcelas proporcionalmente e marca tudo como pago.
    """
    permission_required = 'vendas.can_confirm_quitacao' # <- Permissão customizada

    def post(self, request, pk):
        pagamento = get_object_or_404(Pagamento, pk=pk)

        try:
            with transaction.atomic():
                parcelas_a_confirmar = pagamento.parcelas_pagamento.filter(
                    pagamento_efetuado=True, 
                    pago=False
                ).order_by('numero_parcela')

                num_parcelas = parcelas_a_confirmar.count()

                if num_parcelas == 0:
                    messages.warning(request, "Nenhuma parcela aguardando confirmação de quitação.")
                    return redirect('financeiro:contas_a_receber_update', pk=pagamento.pk)

                # A lógica de cálculo de desconto é executada aqui, no momento da confirmação
                total_restante_original = sum(p.valor for p in parcelas_a_confirmar)
                discount_pct = getattr(pagamento, 'porcentagem_desconto', Decimal('0'))
                discount_amount = (total_restante_original * discount_pct / Decimal('100')).quantize(Decimal('0.01'))
                total_com_desconto = (total_restante_original - discount_amount).quantize(Decimal('0.01'))

                # Lógica de distribuição proporcional (Método do Restante)
                lista_parcelas = list(parcelas_a_confirmar)
                soma_parcial_atualizada = Decimal('0.00')

                if total_restante_original > 0:
                    ratio_desconto = total_com_desconto / total_restante_original
                else:
                    ratio_desconto = Decimal('1')

                data_confirmacao = timezone.now().date()

                # Itera sobre N-1 parcelas
                for parcela in lista_parcelas[:-1]:
                    novo_valor = (parcela.valor * ratio_desconto).quantize(Decimal('0.01'))
                    parcela.valor = novo_valor
                    parcela.pago = True # <- AGORA SIM, marca como PAGO
                    parcela.data_pagamento = data_confirmacao
                    parcela.save(update_fields=['valor', 'pago', 'data_pagamento'])
                    soma_parcial_atualizada += novo_valor
                
                # Processa a última parcela
                if lista_parcelas:
                    ultima_parcela = lista_parcelas[-1]
                    valor_ultima_parcela = total_com_desconto - soma_parcial_atualizada
                    ultima_parcela.valor = valor_ultima_parcela
                    ultima_parcela.pago = True # <- Marca como PAGO
                    ultima_parcela.data_pagamento = data_confirmacao
                    ultima_parcela.save(update_fields=['valor', 'pago', 'data_pagamento'])
                
                # Finalmente, atualiza o Pagamento principal
                pagamento.quitado = True
                pagamento.save(update_fields=['quitado'])

                messages.success(request, f"Quitação do Pagamento #{pagamento.pk} confirmada! {num_parcelas} parcelas foram ajustadas e marcadas como pagas.")

        except Exception:
            logger.exception("Erro ao confirmar a quitação do pagamento %s", pagamento.pk)
            messages.error(request, "❌ Não foi possível confirmar a quitação. Tente novamente ou fale com o suporte.")

        return redirect('financeiro:contas_a_receber_update', pk=pagamento.pk)    
