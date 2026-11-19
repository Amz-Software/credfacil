"""Lojas parceiras e números autenticadores."""
from datetime import date
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from financeiro.forms import RepasseForm
from financeiro.models import Repasse
from vendas.forms import LojaForm, NumeroAutenticadorForm
from vendas.models import Loja, NumeroAutenticador, Venda
from vendas.services import ErroDeNegocio
from vendas.services.lojas import replicar_qr_code_aplicativo, status_repasses_por_loja

from .base import BaseView


logger = logging.getLogger(__name__)


class LojaListView(BaseView, PermissionRequiredMixin, ListView):
    model = Loja
    template_name = 'loja/loja_list.html'
    context_object_name = 'lojas'
    permission_required = 'vendas.view_loja'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        query = Loja.objects.all()
        loja_id = self.request.session.get('loja_id')
        search = self.request.GET.get('search')
        filter_type = self.request.GET.get('filter')
        
        if not user.has_perm('vendas.can_view_all_stores'):
            query = query.filter(id=loja_id)

        if search:
            query = query.filter(nome__icontains=search)
        
        if filter_type == 'pendente':
            query = query.com_repasse_pendente()
        elif filter_type == 'sem_pendente':
            query = query.sem_repasse_pendente()
        
        return query.order_by('nome')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        lojas = list(context['lojas'])
        status = status_repasses_por_loja(lojas)
        for loja in lojas:
            repasses, atrasados = status[loja.id]
            loja.repasses_info = {'repasses': repasses, 'atrasados': atrasados}
        context['lojas'] = lojas
        context['filter'] = self.request.GET.get('filter', '')
        return context


class LojaCreateView(PermissionRequiredMixin, CreateView):
    model = Loja
    form_class = LojaForm
    template_name = 'loja/loja_form.html'
    permission_required = 'vendas.add_loja'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs
    
    def form_valid(self, form):
        messages.success(self.request, 'Loja cadastrada com sucesso')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        messages.error(self.request, 'Erro ao cadastrar loja')
        return super().form_invalid(form)
    
    def get_success_url(self):
        return reverse_lazy('vendas:loja_detail', kwargs={'pk': self.object.id})


class LojaUpdateView(PermissionRequiredMixin, UpdateView):
    model = Loja
    form_class = LojaForm
    template_name = 'loja/loja_form.html'
    permission_required = 'vendas.change_loja'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user_loja'] = self.request.session.get('loja_id')
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        if 'credfacil' not in self.request.POST:
            form.instance.credfacil = self.get_object().credfacil
        messages.success(self.request, 'Loja atualizada com sucesso')
        return super().form_valid(form)
    
    def form_invalid(self, form):
        # Adiciona mensagem de erro se o formulário for inválido
        if form.errors:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(self.request, f"Erro no campo {field}: {error}")
        messages.error(self.request, 'Erro ao atualizar loja')
        return super().form_invalid(form)
    
    def get_success_url(self):
        return reverse_lazy('vendas:loja_detail', kwargs={'pk': self.object.id})


@require_POST
@permission_required('vendas.change_loja', raise_exception=True)
def replicar_qr_code_codigo_aplicativo(request, pk):
    loja = get_object_or_404(Loja, id=pk)
    try:
        replicar_qr_code_aplicativo(loja)
    except ErroDeNegocio as erro:
        messages.error(request, f'❌ {erro.mensagem}')
    else:
        messages.success(request, '✅ QR Code e código do aplicativo replicados com sucesso para outras lojas.')
    return redirect('vendas:loja_list')


class LojaDetailView(PermissionRequiredMixin, DetailView):
    model = Loja
    template_name = 'loja/loja_detail.html'
    permission_required = 'vendas.view_loja'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja = self.object

        contrato = loja.contrato
        context['contrato'] = json.dumps(contrato) if contrato else None

        repasses_qs    = Repasse.objects.filter(loja=loja).select_related('criado_por')
        repasse_paginator = Paginator(repasses_qs, 10)
        context['repasses'] = repasse_paginator.get_page(self.request.GET.get('repasse_page'))

        vendas_qs = Venda.objects.filter(loja=loja, is_deleted=False).select_related('cliente')
        data_inicio = self.request.GET.get('data_inicio', '')
        data_fim = self.request.GET.get('data_fim', '')
        di = parse_date(data_inicio) if data_inicio else None
        df = parse_date(data_fim) if data_fim else None

        if di:
            vendas_qs = vendas_qs.filter(data_venda__date__gte=di)
        if df:
            vendas_qs = vendas_qs.filter(data_venda__date__lte=df)


        total_vendas = vendas_qs.aggregate(qtd=Count('id'))['qtd'] or 0
        valor_total  = vendas_qs.aggregate(val=Sum('pagamentos__valor'))['val'] or 0

        venda_paginator = Paginator(vendas_qs.order_by('-data_venda'), 10)
        context['vendas']      = venda_paginator.get_page(self.request.GET.get('venda_page'))
        context['data_inicio'] = data_inicio
        context['data_fim']    = df

        status_list, atrasados = loja.get_repasses_status(meses_atras=1)
        if di:
            status_list = [r for r in status_list if r['data'] >= parse_date(di)]
        if df:
            status_list = [r for r in status_list if r['data'] <= parse_date(df)]
        context['repasse_status_list'] = status_list
        context['repasse_atrasados']   = sum(1 for r in status_list if not r['feito'] and r['data'] < date.today())
        context['today'] = date.today()

        context['kpi_valor_repasse'] = loja.calcular_valor_repasse(di, df)


        context['repasse_form'] = RepasseForm(initial={'loja': loja})

        context['kpi'] = {
            'qtd_vendas':    total_vendas,
            'valor_total':   valor_total,
            'valor_repasse': context['kpi_valor_repasse'],
        }

        return context


# ── Números Autenticadores ────────────────────────────────────────────────────

class NumeroAutenticadorMixin:
    """Restringe acesso a ANALISTA e ADMINISTRADOR."""
    def dispatch(self, request, *args, **kwargs):
        is_allowed = (
            request.user.is_superuser
            or request.user.groups.filter(name__in=['ANALISTA', 'ADMINISTRADOR']).exists()
        )
        if not is_allowed:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def _get_loja(self):
        loja_id = self.request.session.get('loja_id')
        return get_object_or_404(Loja, pk=loja_id) if loja_id else None


class NumeroAutenticadorListView(LoginRequiredMixin, NumeroAutenticadorMixin, ListView):
    model = NumeroAutenticador
    template_name = 'numeroautenticador/numeroautenticador_list.html'
    context_object_name = 'items'
    paginate_by = 15

    def get_queryset(self):
        loja = self._get_loja()
        qs = NumeroAutenticador.objects.filter(loja=loja) if loja else NumeroAutenticador.objects.all()
        search = self.request.GET.get('search')
        if search:
            qs = qs.filter(numero__icontains=search) | qs.filter(descricao__icontains=search)
        return qs.order_by('numero')


class NumeroAutenticadorCreateView(LoginRequiredMixin, NumeroAutenticadorMixin, CreateView):
    model = NumeroAutenticador
    form_class = NumeroAutenticadorForm
    template_name = 'numeroautenticador/numeroautenticador_form.html'
    success_url = reverse_lazy('vendas:numeroautenticador_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        loja = self._get_loja()
        form.instance.loja = loja
        messages.success(self.request, 'Número autenticador criado com sucesso.')
        return super().form_valid(form)


class NumeroAutenticadorUpdateView(LoginRequiredMixin, NumeroAutenticadorMixin, UpdateView):
    model = NumeroAutenticador
    form_class = NumeroAutenticadorForm
    template_name = 'numeroautenticador/numeroautenticador_form.html'
    success_url = reverse_lazy('vendas:numeroautenticador_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, 'Número autenticador atualizado com sucesso.')
        return super().form_valid(form)


class NumeroAutenticadorDeleteView(LoginRequiredMixin, NumeroAutenticadorMixin, DeleteView):
    model = NumeroAutenticador
    template_name = 'numeroautenticador/numeroautenticador_confirm_delete.html'
    success_url = reverse_lazy('vendas:numeroautenticador_list')

    def form_valid(self, form):
        messages.success(self.request, 'Número autenticador removido.')
        return super().form_valid(form)
