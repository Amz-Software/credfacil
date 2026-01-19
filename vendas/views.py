import logging
import json
import re
import sys
import io
import base64
import calendar
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from collections import defaultdict
from io import BytesIO
from django.db.models import Count, Q
import qrcode
from qrcode import QRCode
from qrcode.constants import ERROR_CORRECT_M

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from accounts.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.timezone import localtime, now
from django.views.generic import TemplateView, ListView, DetailView, CreateView, DeleteView, UpdateView, View, FormView
from django_select2.views import AutoResponseView
from pixqrcodegen import Payload
from estoque.models import Estoque, EstoqueImei
from financeiro.forms import RepasseForm
from financeiro.models import Repasse
from produtos.models import Produto
from vendas.forms import (
    AnaliseCreditoClienteForm, ClienteConsultaForm, ClienteForm, ComprovantesClienteEditForm,
    ComprovantesClienteForm, ContatoAdicionalEditForm, ContatoAdicionalForm, FormaPagamentoEditFormSet,
    InformacaoPessoalEditForm, InformacaoPessoalForm, LojaForm, ProdutoVendaEditFormSet, RelatorioSolicitacoesForm,
    RelatorioVendasForm, VendaForm, VendaDocumentosForm, ProdutoVendaFormSet, FormaPagamentoFormSet, LancamentoForm,
    LancamentoCaixaTotalForm, ClienteTelefoneForm, AnaliseCreditoClienteImeiForm, VendaEdicaoEspecialForm,
    ProdutoVendaEdicaoEspecialFormSet, FormaPagamentoEdicaoEspecialFormSet
)
from .models import (
    AnaliseCreditoCliente, Caixa, Cliente, Loja, Pagamento, Parcela, ProdutoVenda, TipoPagamento, Venda,
    LancamentoCaixa, LancamentoCaixaTotal, StatusPagamento
)
from pypix import Pix
#import q



logger = logging.getLogger(__name__)

class BaseView(View):
    def get_loja(self):
        loja_id = self.request.session.get('loja_id')
        if loja_id:
            return get_object_or_404(Loja, id=loja_id)
        return None

    def get_queryset(self):
        loja = self.get_loja()
        if loja:
            return super().get_queryset().filter(loja=loja)
        
        if not loja:
            raise Http404("Loja não encontrada para o usuário.")

        return super().get_queryset()


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        loja = self._get_active_loja()
        caixa_diario_loja = Caixa.objects.filter(loja=loja).order_by('-data_abertura').first()
        caixa_total = Caixa.objects.all().filter(loja=loja)

        valor_caixa_total = 0
        for caixa in caixa_total:
            valor_caixa_total += caixa.saldo_total_dinheiro
            valor_caixa_total += caixa.entradas
            valor_caixa_total -= caixa.saidas

        caixa_diario_lucro = 0
        if caixa_diario_loja:
            caixa_diario_lucro = (caixa_diario_loja.saldo_total_dinheiro + caixa_diario_loja.entradas) - caixa_diario_loja.saidas

        entrada_caixa_total = LancamentoCaixaTotal.objects.filter(tipo_lancamento='1', loja=loja)
        saida_caixa_total = LancamentoCaixaTotal.objects.filter(tipo_lancamento='2', loja=loja)

        for entrada in entrada_caixa_total:
            valor_caixa_total += entrada.valor

        for saida in saida_caixa_total:
            valor_caixa_total -= saida.valor

        if self.request.user.has_perm('vendas.can_view_your_dashboard'):
            vendas = Venda.objects.filter(loja=loja)

            total_vendas = vendas.count()
            total_de_parcelas_vencidas = 0
            total_de_parcelas_pagas = 0
            total_de_parcelas_a_vencer = 0
            total_pagas = 0
            total_vencidas = 0
            total_a_vencer = 0
            total_geral_parcelas = 0

            for venda in vendas: 
                parcelas = list(Parcela.objects.filter(
                    pagamento__venda=venda,
                    pagamento__tipo_pagamento__nome='IPX',
                    pagamento__desativado=False,
                ).order_by('data_vencimento')[:3])

                # Em devolução: manter pagas; ignorar futuras (vencidas/a vencer)
                parcelas_vencidas = [
                    p for p in parcelas
                    if p.data_vencimento < timezone.now().date()
                    and not p.pago
                    and not p.pagamento_efetuado
                    and not p.pagamento.devolucao
                ]
                parcelas_pagas = [p for p in parcelas if p.pago and not p.pagamento_efetuado]
                parcelas_a_vencer = [
                    p for p in parcelas
                    if p.data_vencimento >= timezone.now().date()
                    and not p.pago
                    and not p.pagamento_efetuado
                    and not p.pagamento.devolucao
                ]

                total_geral_parcelas += len(parcelas)

                qtd_vencidas = len(parcelas_vencidas)
                qtd_pagas = len(parcelas_pagas)
                qtd_a_vencer = len(parcelas_a_vencer)

                total_de_parcelas_vencidas += qtd_vencidas
                total_de_parcelas_pagas += qtd_pagas
                total_de_parcelas_a_vencer += qtd_a_vencer

                valor_vencidas = sum(p.valor for p in parcelas_vencidas)
                valor_pagas = sum(p.valor for p in parcelas_pagas)
                valor_a_vencer = sum(p.valor for p in parcelas_a_vencer)    

                total_pagas += valor_pagas
                total_vencidas += valor_vencidas
                total_a_vencer += valor_a_vencer


            context['total_vendas_loja'] = total_vendas # quantidade de vendas
            context['total_de_parcelas_geral'] = total_geral_parcelas # quantidade total de parcelas
            context['parcelas_vencidas'] = total_de_parcelas_vencidas # quantidade de parcelas vencidas
            context['parcelas_pagas'] = total_de_parcelas_pagas # quantidade de parcelas pagas
            context['parcelas_a_vencer'] = total_de_parcelas_a_vencer  # quantidade de parcelas a vencer

            context['total_geral_parcelas'] = total_pagas + total_vencidas + total_a_vencer # valor total de parcelas
            context['total_pagas'] = total_pagas # valor total de parcelas pagas
            context['total_vencidas'] = total_vencidas # valor total de parcelas vencidas
            context['total_a_vencer'] = total_a_vencer # valor total de parcelas a vencer

            # --- CÁLCULO DOS CLIENTES DESATIVADOS ---
            total_desativados_vencidas = 0
            total_desativados_a_vencer = 0
            qtd_desativados_vencidas = 0
            qtd_desativados_a_vencer = 0

            # Busca parcelas de clientes desativados (apenas não pagas)
            parcelas_desativadas = Parcela.objects.filter(
                pagamento__venda__loja=loja,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__desativado=True,
                pago=False  # Apenas parcelas não pagas
            )

            for parcela in parcelas_desativadas:
                if parcela.data_vencimento < timezone.now().date():
                    total_desativados_vencidas += parcela.valor
                    qtd_desativados_vencidas += 1
                else:
                    total_desativados_a_vencer += parcela.valor
                    qtd_desativados_a_vencer += 1

            # Total de pagamentos desativados
            total_pagamentos_desativados = Pagamento.objects.filter(
                venda__loja=loja,
                tipo_pagamento__nome='IPX',
                desativado=True
            ).count()

            context['total_desativados_vencidas'] = total_desativados_vencidas
            context['total_desativados_a_vencer'] = total_desativados_a_vencer
            context['qtd_desativados_vencidas'] = qtd_desativados_vencidas
            context['qtd_desativados_a_vencer'] = qtd_desativados_a_vencer
            context['total_pagamentos_desativados'] = total_pagamentos_desativados

            # Incluir desativados no gráfico
            total_geral_grafico = float(total_pagas) + float(total_vencidas) + float(total_a_vencer) + float(total_desativados_vencidas) + float(total_desativados_a_vencer)
            pct_pagas = round((float(total_pagas) / total_geral_grafico * 100), 2) if total_geral_grafico else 0
            pct_vencidas = round((float(total_vencidas) / total_geral_grafico * 100), 2) if total_geral_grafico else 0
            pct_desativados = round(((float(total_desativados_vencidas) + float(total_desativados_a_vencer)) / total_geral_grafico * 100), 2) if total_geral_grafico else 0

            context['dash'] = json.dumps({
                'labels': ['Pagas', 'Vencidas', 'Desativados'],
                'data': [pct_pagas, pct_vencidas, pct_desativados],
            })

        context['loja'] = loja
        context['caixa_diario'] = caixa_diario_loja
        context['caixa_diario_lucro'] = caixa_diario_lucro
        context['caixa_total'] = valor_caixa_total

        return context

    def _get_active_loja(self):
        loja_id = self.request.session.get('loja_id')
        loja = Loja.objects.filter(id=loja_id).first() if loja_id else None

        if not loja and self.request.user.is_authenticated:
            loja = self.request.user.lojas.first()
            if not loja and getattr(self.request.user, 'loja_id', None):
                loja = self.request.user.loja

            if loja:
                self.request.session['loja_id'] = loja.id

        if not loja:
            raise Http404("Nenhuma loja vinculada ao usuário.")

        return loja
    

from django.http import JsonResponse, HttpResponse
from django.views import View
from django.template.loader import get_template
from django.template import Context
import weasyprint
from io import BytesIO

class CaixaKpiCountsView(View):
    def get(self, request, *args, **kwargs):
        if request.user.has_perm('vendas.view_all_analise_credito'):
            qs = AnaliseCreditoCliente.objects.all()
        else:
            loja_id = request.session.get('loja_id')
            qs = AnaliseCreditoCliente.objects.filter(loja_id=loja_id)

        status_counts = (
            qs.values('status')
              .annotate(total=Count('id'))
        )
        data = {item['status']: item['total'] for item in status_counts}
        # garantia de zeros
        for code, _ in AnaliseCreditoCliente.STATUS_CHOICES:
            data.setdefault(code, 0)
        return JsonResponse(data)


    

class CaixaListView(BaseView, PermissionRequiredMixin, ListView):
    model = Caixa
    template_name = 'caixa/caixa_list.html'
    context_object_name = 'caixas'
    permission_required = 'vendas.view_caixa'
    
    
    def get_queryset(self):
        query = super().get_queryset()
        data_filter = self.request.GET.get('search')
        loja = self.request.GET.get('loja')
        
        if loja:
            query = query.filter(loja__id=loja)
            
        if data_filter:
            return query.filter(data_abertura=data_filter)
        
        return query.order_by('-criado_em')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.user.has_perm('vendas.can_view_all_stores'):
            context['lojas'] = Loja.objects.all()
        return context

    def post(self, request, *args, **kwargs):
        # Abertura de caixa
        if 'criar_caixa' in request.POST:
            user = request.user
            today = timezone.localtime(timezone.now()).date()

            # Escolhe a loja: do select se tiver permissão, senão da sessão
            if user.has_perm('vendas.can_view_all_stores'):
                loja_id = request.POST.get('loja_id')
            else:
                loja_id = request.session.get('loja_id')
            loja = Loja.objects.get(id=loja_id)

            if not Caixa.caixa_aberto(today, loja):
                Caixa.objects.create(
                    data_abertura=today,
                    criado_por=user,
                    modificado_por=user,
                    loja=loja
                )
                messages.success(request, 'Caixa aberto com sucesso')
            else:
                messages.warning(request, 'Já existe um caixa aberto para hoje')

            return redirect('vendas:caixa_list')

        # Fechamento de caixa (mantido igual)
        if 'fechar_caixa' in request.POST:
            today = timezone.localtime(timezone.now()).date()
            try:
                caixa = Caixa.objects.get(id=request.POST['fechar_caixa'],
                                          loja=request.session.get('loja_id'))
                caixa.data_fechamento = today
                caixa.save(user=request.user)
                messages.success(request, 'Caixa fechado com sucesso')
            except Caixa.DoesNotExist:
                messages.warning(request, 'Não existe caixa aberto para hoje')
            return redirect('vendas:caixa_list')

        return self.get(request, *args, **kwargs)



class CaixaDetailView(PermissionRequiredMixin, DetailView):
    model = Caixa
    template_name = 'caixa/caixa_detail.html'
    permission_required = 'vendas.view_caixa'
    
    def get_context_data(self, **kwargs):
        loja_id = self.request.session.get('loja_id')
        loja = get_object_or_404(Loja, id=loja_id)
        context = super().get_context_data(**kwargs)
        context['vendas'] = self.object.vendas.filter(is_deleted=False).filter(loja=loja)
        context['form_lancamento'] = LancamentoForm()
        context['lancamentos'] = LancamentoCaixa.objects.filter(caixa=self.object)
        return context

    def post(self, request, *args, **kwargs):
        # Pegue o ID do caixa diretamente de kwargs
        caixa_id = kwargs.get('pk')  # O parâmetro é chamado 'pk' na URL

        try:
            # Busque o objeto Caixa
            caixa = Caixa.objects.get(id=caixa_id)
        except Caixa.DoesNotExist:
            messages.error(request, 'Erro: Caixa não existe.')
            return redirect('vendas:caixa_list')  # Ajuste conforme sua necessidade

        # Instancie o formulário com os dados do POST
        form = LancamentoForm(request.POST, user=request.user)

        if form.is_valid():
            # Salve o formulário e associe ao caixa
            lancamento = form.save(commit=False)
            lancamento.caixa = caixa
            lancamento.save()
            messages.success(request, 'Lançamento realizado com sucesso')
            return redirect('vendas:caixa_detail', pk=caixa_id)

        # Caso o formulário seja inválido
        messages.error(request, 'Erro ao realizar lançamento')
        return self.get(request, *args, **kwargs)
    

def lancamento_delete_view(request, pk):
    lancamento = get_object_or_404(LancamentoCaixa, id=pk)
    caixa_id = lancamento.caixa.id
    lancamento.delete()
    messages.success(request, 'Lançamento excluído com sucesso')
    return redirect('vendas:caixa_detail', pk=caixa_id)

def lancamento_total_delete_view(request, pk):
    lancamento = get_object_or_404(LancamentoCaixaTotal, id=pk)
    loja_id = lancamento.loja.id
    lancamento.delete()
    messages.success(request, 'Lançamento excluído com sucesso')
    return redirect('vendas:caixa_total')
    

class ClienteListView(BaseView, PermissionRequiredMixin, ListView):
    model = Cliente
    template_name = 'cliente/cliente_list.html'
    context_object_name = 'items'
    paginate_by = 10
    permission_required = 'vendas.view_cliente'
    

    def get_queryset(self):
        qs = Cliente.objects.all()
        search = self.request.GET.get('search')
        analise_online = self.request.GET.get('analise_online')
        status_app = self.request.GET.get('status_app')
        loja_filter = self.request.GET.get('loja')
        data_inicio = self.request.GET.get('data_inicio')
        data_fim = self.request.GET.get('data_fim')
        vendas_nao_finalizadas = self.request.GET.get('vendas_nao_finalizadas')
        
        if status_app:
            qs = qs.filter(analise_credito__status_aplicativo=status_app).distinct()
            
        if search:
            qs = qs.filter(nome__icontains=search)
            
        if analise_online == '1':
            qs = qs.filter(analise_credito__analise_online=True).distinct()
        elif analise_online == '0':
            qs = qs.filter(analise_credito__analise_online=False).distinct()
            
        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(analise_credito__status=status).distinct()
        
        if loja_filter:
            qs = qs.filter(loja_id=loja_filter)
            
        if data_inicio and data_fim:
            qs = qs.filter(analise_credito__data_analise__range=[data_inicio, data_fim]).distinct()
        elif data_inicio:
            qs = qs.filter(analise_credito__data_analise__gte=data_inicio).distinct()
        elif data_fim:
            qs = qs.filter(analise_credito__data_analise__lte=data_fim).distinct()
            
        if vendas_nao_finalizadas:
            qs = qs.filter(analise_credito__venda__isnull=True).distinct()
            
        if not self.request.user.has_perm('vendas.view_all_analise_credito'):
            loja_id = self.request.session.get('loja_id')
            qs = qs.filter(loja_id=loja_id)
        
        return qs.order_by('-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_id = self.request.session.get('loja_id')
        
        context['loja'] = Loja.objects.get(id=loja_id)
        context['lojas'] = Loja.objects.all()

        if self.request.user.has_perm('vendas.view_all_analise_credito'):
            analises = AnaliseCreditoCliente.objects.all()
        else:
            loja_id = self.request.session.get('loja_id')
            analises = AnaliseCreditoCliente.objects.filter(loja_id=loja_id)

        counts = analises.values('status').annotate(total=Count('id'))
        kpis = {item['status']: item['total'] for item in counts}
        for code, _ in AnaliseCreditoCliente.STATUS_CHOICES:
            kpis.setdefault(code, 0)

        context['kpis'] = kpis
        context['status_choices'] = AnaliseCreditoCliente.STATUS_CHOICES
        context['current_status'] = self.request.GET.get('status', '')
        context['status_app_choices'] = AnaliseCreditoCliente.STATUS_APP_CHOICES
        context['current_status_app'] = self.request.GET.get('status_app', '')
        return context
    
    
    
    # def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
    #     context = super().get_context_data(**kwargs)
    #     context['form_cliente'] = ClienteForm()
    #     context['form_adicional'] = ContatoAdicionalForm() 
    #     context['form_comprovantes'] = ComprovantesClienteForm()
    #     return context
    
    # def post(self, request, *args, **kwargs):
    #     cliente_id = request.POST.get('cliente_id')  # Verifique se há um cliente_id
        
    #     if cliente_id:  # Se cliente_id existe, é uma edição
    #         cliente = Cliente.objects.get(id=cliente_id)
    #         form_cliente = ClienteForm(request.POST, instance=cliente)
            
    #         # Usamos as instâncias existentes de contato e comprovantes para evitar duplicação
    #         form_adicional = ContatoAdicionalForm(request.POST, instance=cliente.contato_adicional)
    #         form_comprovantes = ComprovantesClienteForm(request.POST, request.FILES, instance=cliente.comprovantes)
    #     else:  # Se não, é um novo cadastro
    #         form_cliente = ClienteForm(request.POST)
    #         form_adicional = ContatoAdicionalForm(request.POST)
    #         form_comprovantes = ComprovantesClienteForm(request.POST, request.FILES)
        
    #     if form_cliente.is_valid() and form_adicional.is_valid() and form_comprovantes.is_valid():
    #         cliente = form_cliente.save(commit=False)
    #         endereco = form_adicional.save(commit=False)  # Salve o contato sem commit para associá-lo
    #         comprovantes = form_comprovantes.save(commit=False)  # Salve comprovantes sem commit
    #         loja = Loja.objects.get(id=request.session.get('loja_id'))
    #         cliente.criado_por = request.user
    #         cliente.modificado_por = request.user
    #         cliente.loja = loja
    #         endereco.criado_por = request.user
    #         endereco.modificado_por = request.user
    #         endereco.loja = loja
    #         comprovantes.criado_por = request.user
    #         comprovantes.modificado_por = request.user
    #         comprovantes.loja = loja
            
    #         # Associa as instâncias e depois salva tudo
    #         cliente.contato_adicional = endereco
    #         cliente.comprovantes = comprovantes
            
    #         endereco.save()  # Salva as instâncias associadas
    #         comprovantes.save()
    #         cliente.save()

    #         # Mensagem de sucesso baseada em ação de edição ou criação
    #         if cliente_id:
    #             messages.success(request, 'Cliente atualizado com sucesso')
    #         else:
    #             messages.success(request, 'Cliente cadastrado com sucesso')
                    
    #         return redirect('vendas:cliente_list')
        
    #     # Mensagem de erro e retorno do formulário em caso de falha na validação
    #     messages.error(request, 'Erro ao cadastrar cliente')
    #     return self.get(request, *args, **kwargs)
    

class ClienteCreateView(PermissionRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'cliente/form_cliente.html'
    success_url = reverse_lazy('vendas:cliente_list')
    permission_required = 'vendas.add_cliente'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Buscar loja da sessão
        loja_id = self.request.session.get('loja_id')
        loja = None
        if loja_id:
            try:
                loja = Loja.objects.get(id=loja_id)
            except Loja.DoesNotExist:
                loja = None
        
        context['form_cliente'] = kwargs.get('form_cliente', ClienteForm(user=self.request.user))
        context['form_adicional'] = kwargs.get('form_adicional', ContatoAdicionalForm(user=self.request.user))
        context['form_informacao'] = kwargs.get('form_informacao', InformacaoPessoalForm(user=self.request.user))
        context['form_comprovantes'] = kwargs.get('form_comprovantes', ComprovantesClienteForm(user=self.request.user))
        context['form_analise_credito'] = kwargs.get('form_analise_credito', AnaliseCreditoClienteForm(user=self.request.user, loja=loja))
        
        # Adiciona informação sobre permissão de visualizar consulta Serasa
        context['can_view_consulta_serasa'] = self.request.user.has_perm('vendas.view_consulta_serasa')
        
        produtos = Produto.objects.filter(ativo=True).values('id', 'nome', 'valor_4_vezes', 'valor_6_vezes', 'valor_8_vezes', 'valor_10_vezes', 'entrada_cliente')
        produtos_list = [
            {
                'id': p['id'],
                'nome': p['nome'],
                'valor4': float(p['valor_4_vezes']),
                'valor6': float(p['valor_6_vezes']),
                'valor8': float(p['valor_8_vezes']),
                'valor10': float(p['valor_10_vezes']),
                'entrada': float(p['entrada_cliente']),
            }
            for p in produtos
        ]
        context['produtos_json'] = json.dumps(produtos_list)

        return context

    def post(self, request, *args, **kwargs):
        self.object = None

        # Buscar loja da sessão
        loja_id = request.session.get('loja_id')
        loja = None
        if loja_id:
            try:
                loja = Loja.objects.get(id=loja_id)
            except Loja.DoesNotExist:
                loja = None
        
        # Passando o user para os formulários
        form_cliente = ClienteForm(request.POST, user=request.user)
        form_adicional = ContatoAdicionalForm(request.POST, user=request.user)
        form_informacao = InformacaoPessoalForm(request.POST, user=request.user)
        form_comprovantes = ComprovantesClienteForm(request.POST, request.FILES, user=request.user)
        form_analise_credito = AnaliseCreditoClienteForm(request.POST, user=request.user, loja=loja)

        if all([
            form_cliente.is_valid(),
            form_adicional.is_valid(),
            form_informacao.is_valid(),
            form_comprovantes.is_valid(),
            form_analise_credito.is_valid()
        ]):
            
            contato_adicional_val = form_adicional.cleaned_data.get('contato')
            contato_pessoal_val = form_informacao.cleaned_data.get('contato_pessoal')
            endereco_adicional_val = form_adicional.cleaned_data.get('endereco_adicional').lower()
            endereco_pessoal_val = form_informacao.cleaned_data.get('endereco_pessoal').lower()

            if (contato_adicional_val == contato_pessoal_val) or (endereco_adicional_val == endereco_pessoal_val):
                print("❌ CONDIÇÃO ATINGIDA: Os contatos e endereços adicionais não podem ser iguais.")
                messages.error(request, "❌ Os contatos e endereços adicionais não podem ser iguais.")
                return self.form_invalid(form_cliente)
            
            comprovantes = form_comprovantes.save()
            contato_adicional = form_adicional.save()
            informacao = form_informacao.save()
            loja_id = request.session.get('loja_id')

            # Atribui os comprovantes ao form_cliente antes de salvar
            cliente = form_cliente.save(commit=False)
            cliente.criado_por = request.user
            cliente.modificado_por = request.user
            cliente.loja = Loja.objects.get(id=loja_id)
            
            cliente.contato_adicional = contato_adicional
            cliente.informacao_pessoal = informacao
            cliente.comprovantes = comprovantes
            cliente.save()

            try:
                loja = Loja.objects.get(id=loja_id)
            except Loja.DoesNotExist:
                print(f"❌ Loja com ID {loja_id} não encontrada")
                return self.form_invalid(form_cliente)

            analise = form_analise_credito.save(commit=False)
            analise.cliente = cliente
            analise.loja = loja
            analise.criado_por = request.user
            analise.modificado_por = request.user
            analise.save(user=request.user)
            print("✅ Análise de crédito salva")

            messages.success(request, "✅ Soliticitação cadastrado com sucesso")
            return redirect(self.success_url)

        else:
            print("❌ Um ou mais formulários são inválidos:")
            print("form_cliente errors:", form_cliente.errors)
            print("form_adicional errors:", form_adicional.errors)
            print("form_informacao errors:", form_informacao.errors)
            print("form_comprovantes errors:", form_comprovantes.errors)
            print("form_analise_credito errors:", form_analise_credito.errors)
            
            for form in [form_cliente, form_adicional, form_informacao, form_comprovantes, form_analise_credito]:   
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"Erro no campo '{field}': {error}")
                        
            messages.error(request, "❌ Erro ao cadastrar Soliticitação. Verifique os dados e tente novamente.")

        # Renderiza novamente com os erros
        context = self.get_context_data(
            form_cliente=form_cliente,
            form_adicional=form_adicional,
            form_informacao=form_informacao,
            form_comprovantes=form_comprovantes,
            form_analise_credito=form_analise_credito,
        )
        return self.render_to_response(context)

class ClienteUpdateView(PermissionRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'cliente/form_cliente.html'
    success_url = reverse_lazy('vendas:cliente_list')
    permission_required = 'vendas.change_cliente'
    context_object_name = 'cliente'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente = self.get_object()
        
        # Buscar loja da sessão
        loja_id = self.request.session.get('loja_id')
        loja = None
        if loja_id:
            try:
                loja = Loja.objects.get(id=loja_id)
            except Loja.DoesNotExist:
                loja = None

        context['form_cliente'] = kwargs.get('form_cliente', ClienteForm(instance=cliente, user=self.request.user))  # Alteração aqui
        context['form_adicional'] = kwargs.get('form_adicional', ContatoAdicionalForm(instance=cliente.contato_adicional, user=self.request.user))
        context['form_informacao'] = kwargs.get('form_informacao', InformacaoPessoalForm(instance=cliente.informacao_pessoal, user=self.request.user))
        context['form_comprovantes'] = kwargs.get('form_comprovantes', ComprovantesClienteForm(instance=cliente.comprovantes, user=self.request.user))
        context['form_analise_credito'] = kwargs.get('form_analise_credito', AnaliseCreditoClienteForm(instance=cliente.analise_credito, user=self.request.user, loja=loja))
        context['cliente_id'] = cliente.id
        
        # Adiciona informação sobre permissão de visualizar consulta Serasa
        context['can_view_consulta_serasa'] = self.request.user.has_perm('vendas.view_consulta_serasa')
        
        analise = get_object_or_404(AnaliseCreditoCliente, cliente=self.object)
        # expõe no template
        context['analise_credito'] = analise
        
        context['status_app_choices'] = AnaliseCreditoCliente.STATUS_APP_CHOICES

        produtos = Produto.objects.all().values(
            'id',
            'nome',
            'valor_4_vezes',
            'valor_6_vezes',
            'valor_8_vezes',
            'valor_10_vezes',
            'entrada_cliente'
        )
        produtos_list = [
            {
                'id': p['id'],
                'nome': p['nome'],
                'valor4': float(p['valor_4_vezes']),
                'valor6': float(p['valor_6_vezes']),
                'valor8': float(p['valor_8_vezes']),
                'valor10': float(p['valor_10_vezes']),
                'entrada': float(p['entrada_cliente']),
            }
            for p in produtos
        ]
        context['produtos_json'] = json.dumps(produtos_list)

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user
        
        # Verifica se o usuário é analista
        is_analista = user.groups.filter(name='ANALISTA').exists()
        
        # Verifica se a venda já foi gerada
        venda_gerada = self.object.analise_credito.venda is not None

        # Se não é analista e não tem permissão de mudar status, só pode editar se estiver em análise
        if not is_analista and not user.has_perm('vendas.change_status_analise') and not self.object.analise_credito.status == 'EA':
            messages.warning(request, "❌ Somente Solicitacao em análise de crédito em andamento podem ser editados.")
            return redirect(self.success_url)
        
        # Se a venda foi gerada, apenas usuários com permissão específica podem editar
        if venda_gerada:
            if not user.has_perm('vendas.can_edit_finished_sale'):
                messages.warning(request, "❌ Somente usuários com permissão específica podem editar solicitações após a venda ser gerada.")
                return redirect(self.success_url)

        # Buscar loja da sessão
        loja_id = request.session.get('loja_id')
        loja = None
        if loja_id:
            try:
                loja = Loja.objects.get(id=loja_id)
            except Loja.DoesNotExist:
                loja = None
        
        form_cliente = ClienteForm(request.POST, instance=self.object, user=user)
        form_adicional = ContatoAdicionalForm(request.POST, instance=self.object.contato_adicional, user=user)
        form_informacao = InformacaoPessoalForm(request.POST, instance=self.object.informacao_pessoal, user=user)
        form_comprovantes = ComprovantesClienteForm(request.POST, request.FILES, instance=self.object.comprovantes, user=user)
        form_analise_credito = AnaliseCreditoClienteForm(request.POST, instance=self.object.analise_credito, user=request.user, loja=loja)

        if all([
            form_cliente.is_valid(),
            form_adicional.is_valid(),
            form_informacao.is_valid(),
            form_comprovantes.is_valid(),
            form_analise_credito.is_valid()
        ]):
            
            contato_adicional_val = form_adicional.cleaned_data.get('contato')
            contato_pessoal_val = form_informacao.cleaned_data.get('contato_pessoal')
            endereco_adicional_val = form_adicional.cleaned_data.get('endereco_adicional').lower()
            endereco_pessoal_val = form_informacao.cleaned_data.get('endereco_pessoal').lower()

            if (contato_adicional_val == contato_pessoal_val) or (endereco_adicional_val == endereco_pessoal_val):
                print("❌ CONDIÇÃO ATINGIDA: Os contatos e endereços adicionais não podem ser iguais.")
                messages.error(request, "❌ Os contatos e endereços adicionais não podem ser iguais.")
                return self.form_invalid(form_cliente)
            
            
            contato_adicional = form_adicional.save()
            informacao = form_informacao.save()
            comprovantes = form_comprovantes.save()
            analise_credito = form_analise_credito.save()

            cliente = form_cliente.save(commit=False)
            cliente.contato_adicional = contato_adicional
            cliente.comprovantes = comprovantes
            cliente.save(user=user)
            messages.success(request, "✅ Soliticitação atualizada com sucesso")
            
            # Verifica se deve redirecionar para aprovação
            aprovar_url = request.POST.get('aprovar_apos_salvar')
            if aprovar_url:
                return redirect(aprovar_url)
            
            return redirect(self.success_url)
        else:
            for form in [form_cliente, form_adicional, form_comprovantes, form_analise_credito]:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f"Erro no campo '{field}': {error}")
            messages.error(request, "❌ Erro ao atualizar Soliticitação. Verifique os dados e tente novamente.")

        context = self.get_context_data(
            form_cliente=form_cliente,
            form_adicional=form_adicional,
            form_comprovantes=form_comprovantes,
            form_analise_credito=form_analise_credito,
        )
        return self.render_to_response(context)
    
class ClienteUpdateImeiTelefoneView(PermissionRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = 'cliente/form_cliente_imei_telefone.html'
    success_url = reverse_lazy('vendas:cliente_list')
    permission_required = 'vendas.change_cliente'
    context_object_name = 'cliente'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cliente = self.get_object()

        context['form_cliente'] = kwargs.get('form_cliente', ClienteTelefoneForm(instance=cliente, user=self.request.user))
        context['form_adicional'] = kwargs.get('form_adicional', ContatoAdicionalEditForm(instance=cliente.contato_adicional, user=self.request.user))
        context['form_informacao'] = kwargs.get('form_informacao', InformacaoPessoalEditForm(instance=cliente.informacao_pessoal, user=self.request.user))
        context['form_comprovantes'] = kwargs.get('form_comprovantes', ComprovantesClienteEditForm(instance=cliente.comprovantes, user=self.request.user))
        context['form_analise_credito'] = kwargs.get('form_analise_credito', AnaliseCreditoClienteImeiForm(instance=cliente.analise_credito, user=self.request.user))
        context['cliente_id'] = cliente.id
        context['analise_credito'] = cliente.analise_credito
        context['status_app_choices'] = AnaliseCreditoCliente.STATUS_APP_CHOICES

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        form_cliente = ClienteTelefoneForm(request.POST, instance=self.object, user=user)
        form_analise_credito = AnaliseCreditoClienteImeiForm(request.POST, instance=self.object.analise_credito, user=request.user)

        if form_cliente.is_valid() and form_analise_credito.is_valid():
            form_analise_credito.save()
            cliente = form_cliente.save(commit=False)
            cliente.save(user=user)
            messages.success(request, "✅ Soliticitação atualizada com sucesso")
            return redirect(self.success_url)
        else:
            messages.error(request, "❌ Erro ao atualizar Soliticitação. Verifique os dados e tente novamente.")

        context = self.get_context_data(
            form_cliente=form_cliente,
            form_analise_credito=form_analise_credito,
        )
        return self.render_to_response(context)
    

class ClienteInstallAppView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        analise_credito = cliente.analise_credito
        loja_id = request.session.get('loja_id')
        # opcional: valida se é da mesma loja
        if cliente.loja_id != loja_id:
            messages.error(request, "Ação não autorizada para esta loja.")
            return redirect('vendas:cliente_list')

        analise_credito.status_aplicativo = 'C'
        analise_credito.save()
        messages.success(request, "Status alterado para Confirmação Pendente.")
        return redirect('vendas:cliente_list')


class ClienteConfirmInstalledView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        analise_credito = cliente.analise_credito
        
        # Marcar como confirmação pendente (aguardando analista informar IMEI)
        analise_credito.status_aplicativo = 'C'
        analise_credito.save()
        
        # Enviar notificação para analistas
        from notifications.signals import notify
        from notificacao.utils import enviar_ws_para_usuario
        
        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        
        verb = f'Vendedor confirmou instalação do app para cliente {cliente_nome.capitalize()}.'
        description = f'Aguardando analista informar IMEI. Loja: {loja.nome.capitalize()}.'
        
        # Notificar analistas e administradores
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=request.user.id)
        )
        
        for user in usuarios_para_notificar:
            notify.send(
                analise_credito,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise_credito,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )
        
        messages.success(request, "✅ Instalação confirmada! Aguardando analista informar IMEI.")
        return redirect('vendas:cliente_list')
    

class ClienteStatusAppUpdateView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        new_status = request.POST.get('status_app')
        analise_credito = cliente.analise_credito

        valid = dict(AnaliseCreditoCliente.STATUS_APP_CHOICES).keys()
        if new_status in valid:
            analise_credito.status_aplicativo = new_status
            analise_credito.save()
            messages.success(request, "Status do aplicativo atualizado para %s." %
                              analise_credito.get_status_aplicativo_display())
        else:
            messages.error(request, "Status inválido.")
        # volta para a página de edição
        return redirect('vendas:cliente_update', pk=pk)



def calcular_data_primeira_parcela(data_pagamento_str):
    """
    Retorna a data com o dia escolhido (01, 10 ou 20) mais distante possível,
    mas ainda dentro de até 40 dias após a data da compra.
    """
    hoje = timezone.now().date()
    dia_escolhido = int(data_pagamento_str)
    max_dias = 40
    ano, mes = hoje.year, hoje.month

    melhor_data = None
    maior_diferenca = -1

    # Verifica até 3 meses à frente
    for i in range(3):
        novo_mes = mes + i
        novo_ano = ano + (novo_mes - 1) // 12
        novo_mes = ((novo_mes - 1) % 12) + 1

        # Verifica se o mês tem o dia escolhido
        ultimo_dia_mes = calendar.monthrange(novo_ano, novo_mes)[1]
        dia_real = min(dia_escolhido, ultimo_dia_mes)

        data_candidata = date(novo_ano, novo_mes, dia_real)
        dias_ate_parcela = (data_candidata - hoje).days

        # Valida se está dentro do prazo
        if 0 < dias_ate_parcela <= max_dias:
            if dias_ate_parcela > maior_diferenca:
                melhor_data = data_candidata
                maior_diferenca = dias_ate_parcela

    return melhor_data


def criar_parcelas(pagamento, loja):
    """
    Gera cada vencimento mantendo o dia fixo (ou último do mês se faltar).
    """
    Parcela.objects.filter(pagamento=pagamento).delete()
    dia = pagamento.data_primeira_parcela.day

    for n in range(1, pagamento.parcelas + 1):
        # calcula ano/mes de cada parcela
        month_offset = pagamento.data_primeira_parcela.month - 1 + (n - 1)
        ano = pagamento.data_primeira_parcela.year + month_offset // 12
        mes = month_offset % 12 + 1

        ultimo = calendar.monthrange(ano, mes)[1]
        venc_dia = min(dia, ultimo)
        data_venc = date(ano, mes, venc_dia)

        Parcela.objects.create(
            loja=loja,
            pagamento=pagamento,
            numero_parcela=n,
            valor=pagamento.valor_parcela,
            data_vencimento=data_venc,
            criado_por=pagamento.criado_por,
            modificado_por=pagamento.modificado_por
        )
        

@transaction.atomic
@permission_required('vendas.add_venda', raise_exception=True)
def gerar_venda(request, cliente_id):
    if request.method != 'POST':
        return redirect('vendas:cliente_list')

    cliente = get_object_or_404(Cliente, id=cliente_id)
    loja = get_object_or_404(Loja, id=request.session.get('loja_id'))
    credfacil = get_object_or_404(Loja, credfacil=True)
    
    if not credfacil or not loja or not cliente:
        messages.error(request, "❌ Loja ou cliente não encontrado.")
        return redirect('vendas:cliente_list')

    # --- Validação: clientes com mesmo CPF precisam ter ao menos 3 parcelas pagas em cada venda anterior ---
    cpf_limpo = re.sub(r'\D', '', cliente.cpf)

    vendas_com_poucas_parcelas = (
        Venda.objects
        .filter(cliente__cpf=cpf_limpo, is_deleted=False)
        .annotate(
            parcelas_pagas=Count(
                'pagamentos__parcelas_pagamento',
                filter=Q(
                    pagamentos__tipo_pagamento__nome__iexact='IPX',
                    pagamentos__parcelas_pagamento__pago=True
                ),
                distinct=True
            )
        )
        .filter(parcelas_pagas__lt=3)
    )

    if vendas_com_poucas_parcelas.exists():
        messages.error(
            request,
            "❌ Para gerar uma nova venda, cada venda anterior do mesmo CPF deve ter pelo menos 3 parcelas pagas."
        )
        return redirect('vendas:cliente_list')

    # Valida análise de crédito
    analise = cliente.analise_credito
    if not analise or analise.status != 'A':
        messages.error(request, "❌ Análise de crédito não aprovada para o cliente.")
        return redirect('vendas:cliente_list')
    if not analise.imei:
        messages.error(request, "❌ Nenhum IMEI associado à análise de crédito. Informe o IMEI antes de gerar a venda.")
        return redirect('vendas:cliente_update', pk=cliente.pk)
    # Para produtos que não são iPhone, exigimos que o app esteja instalado ('I')
    if not getattr(analise.produto, 'is_iphone', False) and analise.status_aplicativo != 'I':
        messages.error(request, "❌ Aplicativo não está instalado. Confirme a instalação antes de gerar a venda.")
        return redirect('vendas:cliente_update', pk=cliente.pk)
    if analise.venda:
        messages.error(request, "❌ Essa solicitação já foi convertida em venda.")
        return redirect('vendas:cliente_list')

    # Verifica caixa aberto para a loja da análise
    caixa = Caixa.objects.filter(
        loja=analise.loja,
        data_fechamento__isnull=True
    ).first()
    if not caixa:
        messages.error(request, f"❌ Nenhum caixa aberto encontrado para a loja {analise.loja.nome}.")
        return redirect('vendas:cliente_list')
    if not analise or analise.status != 'A':
        messages.error(request, "❌ Análise de crédito não aprovada para o cliente.")
        return redirect('vendas:cliente_list')
    if not analise.imei:
        messages.error(request, "❌ Nenhum IMEI associado à análise de crédito. Informe o IMEI antes de gerar a venda.")
        return redirect('vendas:cliente_update', pk=cliente.pk)
    # Para produtos que não são iPhone, exigimos que o app esteja instalado ('I')
    if not getattr(analise.produto, 'is_iphone', False) and analise.status_aplicativo != 'I':
        messages.error(request, "❌ Aplicativo não está instalado. Confirme a instalação antes de gerar a venda.")
        return redirect('vendas:cliente_update', pk=cliente.pk)
    if analise.venda:
        messages.error(request, "❌ Essa solicitação já foi convertida em venda.")
        return redirect('vendas:cliente_list')

    produto = analise.produto
    imei = analise.imei

    # Validações específicas para fluxo iPhone
    if getattr(produto, 'is_iphone', False):
        # Deve haver email/senha iCloud
        if not analise.email_icloud or not analise.senha_icloud:
            messages.error(request, "❌ Para gerar venda de iPhone, Email e Senha iCloud devem estar preenchidos na análise.")
            return redirect('vendas:cliente_update', pk=cliente.pk)

        # Deve ter sido configurado pelo vendedor
        if not analise.icloud_configurado_vendedor:
            messages.error(request, "❌ iCloud ainda não foi configurado pelo vendedor. Complete o fluxo antes de gerar a venda.")
            return redirect('vendas:cliente_update', pk=cliente.pk)

        # Deve ter confirmação do analista
        if not analise.icloud_confirmado_analista:
            messages.error(request, "❌ iCloud não confirmado pelo analista. Aguarde confirmação antes de gerar a venda.")
            return redirect('vendas:cliente_update', pk=cliente.pk)

    # Verifica se o IMEI já está sendo usado em outra venda (único)
    if ProdutoVenda.objects.filter(imei=imei.imei).exists():
        messages.error(request, f"❌ IMEI {imei.imei} já está sendo usado em outra venda. IMEI deve ser único.")
        return redirect('vendas:cliente_update', pk=cliente.pk)

    # Cria venda
    venda = Venda.objects.create(
        loja=analise.loja,  # Usa a loja da análise de crédito
        cliente=cliente,
        vendedor=request.user,
        caixa=caixa,
        repasse_logista=produto.valor_repasse_logista,
        observacao=analise.observacao,
        criado_por=request.user,
        modificado_por=request.user,
        criado_em=timezone.now(),
        modificado_em=timezone.now()
    )
    analise.venda = venda
    analise.save()
    
    porcentagem_desconto = 0
    
    # Define valores e número de parcelas
    if analise.numero_parcelas == '4':
        valor_credfacil = produto.valor_4_vezes
        parcelas = 4
        porcentagem_desconto = credfacil.porcentagem_desconto_4
    elif analise.numero_parcelas == '6':
        valor_credfacil = produto.valor_6_vezes
        parcelas = 6
        porcentagem_desconto = credfacil.porcentagem_desconto_6
    elif analise.numero_parcelas == '8':
        valor_credfacil = produto.valor_8_vezes
        parcelas = 8
        porcentagem_desconto = credfacil.porcentagem_desconto_8
    elif analise.numero_parcelas == '10':
        valor_credfacil = produto.valor_10_vezes
        parcelas = 10
        porcentagem_desconto = credfacil.porcentagem_desconto_10

    # Cria ProdutoVenda
    ProdutoVenda.objects.create(
        loja=analise.loja,  # Usa a loja da análise de crédito
        venda=venda,
        produto=produto,
        imei=imei.imei,
        valor_unitario=valor_credfacil,
        quantidade=1,
        valor_desconto=0
    )

    # IMEI é automaticamente marcado como vendido via signal

    # Pagamentos
    tipo_entrada = TipoPagamento.objects.get(nome__iexact='ENTRADA')
    tipo_credfacil = TipoPagamento.objects.get(nome__iexact='IPX')

    pagamento_entrada = Pagamento.objects.create(
        loja=analise.loja,  # Usa a loja da análise de crédito
        venda=venda,
        tipo_pagamento=tipo_entrada,
        valor=produto.entrada_cliente,
        parcelas=1,
        data_primeira_parcela=timezone.now().date()
    )

    data1 = calcular_data_primeira_parcela(analise.data_pagamento)
    pagamento_credfacil = Pagamento.objects.create(
        loja=analise.loja,  # Usa a loja da análise de crédito
        venda=venda,
        tipo_pagamento=tipo_credfacil,
        valor=valor_credfacil,
        parcelas=parcelas,
        data_primeira_parcela=data1,
        porcentagem_desconto=porcentagem_desconto
    )

    criar_parcelas(pagamento_entrada, analise.loja)
    criar_parcelas(pagamento_credfacil, analise.loja)

    messages.success(request, f"✅ Venda criada para o cliente {cliente.nome}!")
    return redirect('vendas:cliente_list')


@permission_required('vendas.change_status_analise', raise_exception=True)
def aprovar_analise_credito(request, id):
    user = request.user
    if not user.has_perm('vendas.change_status_analise'):
        messages.error(request, 'Você não tem permissão para aprovar análises de crédito')
        return redirect('vendas:cliente_list')
    try:
        analise = AnaliseCreditoCliente.objects.get(id=id)
        
        # Verificar se é iPhone e se tem email/senha iCloud
        if analise.produto.is_iphone:
            if not analise.email_icloud or not analise.senha_icloud:
                messages.error(request, '❌ Para aprovar iPhone, é necessário informar Email e Senha iCloud na solicitação.')
                return redirect('vendas:cliente_update', pk=analise.cliente.pk)
        
        analise.aprovar(user=request.user)
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        messages.success(request, '✅ Análise de crédito aprovada com sucesso')
    except AnaliseCreditoCliente.DoesNotExist:
        messages.error(request, 'Análise de crédito não encontrada')

    return redirect('vendas:cliente_list')


@permission_required('vendas.change_analisecreditocliente', raise_exception=True)
def cancelar_analise_credito(request, id):
    user = request.user
    if not user.has_perm('vendas.change_status_analise'):
        messages.error(request, 'Você não tem permissão para cancelar análises de crédito')
        return redirect('vendas:cliente_list')
    try:
        analise = AnaliseCreditoCliente.objects.get(id=id)
        analise.cancelar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        messages.success(request, 'Análise de crédito cancelada com sucesso')
    except AnaliseCreditoCliente.DoesNotExist:
        messages.error(request, 'Análise de crédito não encontrada')

    return redirect('vendas:cliente_list')

@permission_required('vendas.change_status_analise', raise_exception=True)
def reprovar_analise_credito(request, id):
    user = request.user
    if not user.has_perm('vendas.change_status_analise'):
        messages.error(request, 'Você não tem permissão para reprovar análises de crédito')
        return redirect('vendas:cliente_list')
    try:
        analise = AnaliseCreditoCliente.objects.get(id=id)
        analise.reprovar()
        analise.modificado_por = request.user
        analise.modificado_em = timezone.now()
        analise.save()
        messages.success(request, 'Análise de crédito reprovada com sucesso')
    except AnaliseCreditoCliente.DoesNotExist:
        messages.error(request, 'Análise de crédito não encontrada')

    return redirect('vendas:cliente_list')
    

def cliente_editar_view(request):
    cliente_id = request.GET.get('cliente_id')
    cliente = get_object_or_404(Cliente, id=cliente_id)
    cliente.nascimento = cliente.nascimento.strftime('%Y-%m-%d')
    form_cliente = ClienteForm(instance=cliente, user=request.user)
    form_adicional = ContatoAdicionalForm(instance=cliente.contato_adicional)
    form_comprovantes = ComprovantesClienteForm(instance=cliente.comprovantes, user=request.user)
    
    return render(request, 'cliente/form_cliente.html', {
        'form_cliente': form_cliente,
        'form_adicional': form_adicional,
        'form_comprovantes': form_comprovantes,
        'cliente_id': cliente_id,
    })

class VendaListView(BaseView, PermissionRequiredMixin, ListView):
    model = Venda
    template_name = 'venda/venda_list.html'
    context_object_name = 'vendas'
    paginate_by = 10
    permission_required = 'vendas.view_venda'
    
    def get_queryset(self):
        query = Venda.objects.all()
        data_filter = self.request.GET.get('search')
        loja = self.request.GET.get('loja_id')
        cliente_nome = self.request.GET.get('cliente_nome')
        vendas_canceladas = self.request.GET.get('vendas_canceladas')
        vendas_trocadas = self.request.GET.get('vendas_trocadas')
        
        if loja:
            query = query.filter(loja__id=loja)
        if data_filter:
            query = query.filter(data_venda=data_filter)
        if cliente_nome:
            query = query.filter(cliente__nome__icontains=cliente_nome)
        if vendas_canceladas:
            query = query.filter(is_deleted=True)
        if vendas_trocadas:
            query = query.filter(is_trocado=True)
        
        if not self.request.user.has_perm('vendas.can_view_all_sales'):
            loja_id = self.request.session.get('loja_id')
            query = query.filter(loja_id=loja_id)
        
        return query.order_by('-criado_em')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_id = self.request.session.get('loja_id')
        context['lojas'] = Loja.objects.all()
        context['loja_selecionada'] = loja_id
        return context

class VendaCreateView(PermissionRequiredMixin, CreateView):
    model = Venda
    form_class = VendaForm
    template_name = 'venda/venda_create.html'
    success_url = reverse_lazy('vendas:venda_list')
    permission_required = 'vendas.add_venda'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['loja'] = self.request.session.get('loja_id')
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_id = self.request.session.get('loja_id')
        if self.request.POST:
            context['produto_venda_formset'] = ProdutoVendaFormSet(self.request.POST, form_kwargs={'loja': loja_id})
            context['pagamento_formset'] = FormaPagamentoFormSet(self.request.POST, form_kwargs={'loja': loja_id})
        else:
            context['produto_venda_formset'] = ProdutoVendaFormSet(form_kwargs={'loja': loja_id})
            context['pagamento_formset'] = FormaPagamentoFormSet(form_kwargs={'loja': loja_id})
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        produto_venda_formset = context['produto_venda_formset']
        pagamento_formset = context['pagamento_formset']
        loja = Loja.objects.get(id=self.request.session.get('loja_id'))

        if not (produto_venda_formset.is_valid() and pagamento_formset.is_valid() and form.is_valid()):
            return self.form_invalid(form)

        if not Caixa.caixa_aberto(localtime(now()).date(), loja):
            messages.warning(self.request, 'Não é possível realizar vendas com a loja bloqueada!')
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                self._salvar_venda(form, loja)
                self._processar_produtos(produto_venda_formset, loja)
                self._processar_pagamentos(pagamento_formset, loja)
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f"Erro ao processar a venda: {str(e)}")
            return self.form_invalid(form)

    def _salvar_venda(self, form, loja):
        form.instance.loja = loja
        form.instance.criado_por = self.request.user
        form.instance.modificado_por = self.request.user
        form.instance.caixa = Caixa.objects.filter(data_abertura=localtime(now()).date(), loja=loja).order_by('-criado_em').first()
        form.instance.data_venda = localtime(now())
        self.object = form.save()

    def _processar_produtos(self, formset, loja):
        for produto_venda in formset.save(commit=False):
            produto = produto_venda.produto
            quantidade = produto_venda.quantidade
            imei = produto_venda.imei

            self._validar_estoque(produto, quantidade, loja)
            if produto.tipo.numero_serial:
                self._validar_imei(produto, imei)
            self._atualizar_estoque(produto, quantidade, loja)

            produto_venda.venda = self.object
            produto_venda.loja = loja
            produto_venda.save()

    # Métodos de validação de estoque e IMEI removidos - não são mais necessários

    def _processar_pagamentos(self, formset, loja):
        for pagamento in formset.save(commit=False):
            pagamento.venda = self.object
            pagamento.loja = loja
            pagamento.save()


class VendaUpdateView(PermissionRequiredMixin, UpdateView):
    model = Venda
    form_class = VendaForm
    template_name = 'venda/venda_edit.html'
    permission_required = 'vendas.change_venda'
    
    def get_success_url(self):
        return reverse_lazy('vendas:venda_update', kwargs={'pk': self.object.id})

    def get_form_kwargs(self):
        """Passa a loja para o form."""
        kwargs = super().get_form_kwargs()
        loja_id = self.request.session.get('loja_id')
        kwargs['loja'] = loja_id
        return kwargs

    def get_context_data(self, **kwargs):
        """Carrega os formsets de produtos e pagamentos."""
        context = super().get_context_data(**kwargs)
        loja_id = self.request.session.get('loja_id')
        self.request.session['venda_id'] = self.object.id # Guarda o ID da venda na sessão

        if self.request.POST:
            context['produto_venda_formset'] = ProdutoVendaEditFormSet(
                self.request.POST,
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )
            context['pagamento_formset'] = FormaPagamentoEditFormSet(
                self.request.POST,
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )
        else:
            context['produto_venda_formset'] = ProdutoVendaEditFormSet(
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )
            context['pagamento_formset'] = FormaPagamentoEditFormSet(
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )

        return context

    def form_valid(self, form):
        """Valida os formsets e chama processamento das regras."""
        context = self.get_context_data()
        produto_venda_formset = context['produto_venda_formset']
        pagamento_formset = context['pagamento_formset']
        loja_id = self.request.session.get('loja_id')

        # Verifica se a loja existe
        try:
            loja = Loja.objects.get(id=loja_id)
        except Loja.DoesNotExist:
            messages.error(self.request, "Loja não encontrada")
            logger.error("Loja com id %s não encontrada", loja_id)
            return self.form_invalid(form)

        # Verifica se o caixa está aberto
        if not Caixa.caixa_aberto(localtime(now()).date(), loja):
            messages.warning(self.request, 'Não é possível editar vendas com a loja bloqueada!')
            logger.warning("Tentativa de editar venda com caixa fechado para a loja %s", loja)
            return self.form_invalid(form)

        # Verifica a validade do formulário e dos formsets
        if not form.is_valid():
            logger.error("Formulário principal com erros: %s", form.errors)
        if not produto_venda_formset.is_valid():
            logger.error("ProdutoVendaFormSet com erros: %s", produto_venda_formset.errors)
        if not pagamento_formset.is_valid():
            logger.error("FormaPagamentoFormSet com erros: %s", pagamento_formset.errors)

        if not (form.is_valid() and produto_venda_formset.is_valid() and pagamento_formset.is_valid()):
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                # Atualiza dados básicos da venda
                self._atualizar_venda(form, loja)
                # Processa produtos (incluindo estoque e IMEI)
                self._processar_produtos(produto_venda_formset, loja)
                # Processa pagamentos
                self._processar_pagamentos(pagamento_formset, loja)
                messages.success(self.request, 'Venda atualizada com sucesso')
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f"Erro ao processar a venda: {str(e)}")
            logger.exception("Erro ao processar a venda: %s", e)
            return self.form_invalid(form)

    def _atualizar_venda(self, form, loja):
        """Salva a instância da venda com possíveis alterações."""
        form.instance.loja = loja
        form.instance.modificado_por = self.request.user
        self.object = form.save()

    def _processar_produtos(self, formset, loja):
        """Cria/atualiza/remove itens de venda, validando e atualizando estoques."""
        produtos_modificados = formset.save(commit=False)

        # 1) Deletar itens marcados para exclusão
        for deletado in formset.deleted_objects:
            logger.debug("Deletando produto venda: %s", deletado)
            # Restauração de IMEI removida - não é mais necessária
            deletado.delete()

        # 2) Salvar/atualizar itens (novos ou já existentes)
        for produto_venda in produtos_modificados:
            produto = produto_venda.produto
            quantidade = produto_venda.quantidade
            imei = produto_venda.imei

            # Validações de estoque e IMEI removidas - não são mais necessárias

            produto_venda.venda = self.object
            produto_venda.loja = loja
            produto_venda.save()

        formset.save_m2m()

    def _processar_pagamentos(self, formset, loja):
        """Processa pagamentos do formset, incluindo exclusão e criação/atualização."""
        pagamentos_modificados = formset.save(commit=False)

        # Remover pagamentos excluídos
        for deletado in formset.deleted_objects:
            deletado.delete()

        # Salvar/atualizar pagamentos
        for pagamento in pagamentos_modificados:
            pagamento.venda = self.object
            pagamento.loja = loja
            pagamento.save()

        formset.save_m2m()

    # Métodos auxiliares de estoque e IMEI


class VendaEdicaoEspecialView(PermissionRequiredMixin, UpdateView):
    model = Venda
    form_class = VendaEdicaoEspecialForm
    template_name = 'venda/venda_edit_especial.html'
    permission_required = 'vendas.can_edit_imei_valores_venda'

    def get_success_url(self):
        return reverse_lazy('vendas:venda_edicao_especial', kwargs={'pk': self.object.id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_id = self.object.loja.id
        self.request.session['venda_id'] = self.object.id

        if self.request.POST:
            context['produto_venda_formset'] = ProdutoVendaEdicaoEspecialFormSet(
                self.request.POST,
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )
            context['pagamento_formset'] = FormaPagamentoEdicaoEspecialFormSet(
                self.request.POST,
                instance=self.object
            )
        else:
            context['produto_venda_formset'] = ProdutoVendaEdicaoEspecialFormSet(
                instance=self.object,
                form_kwargs={'loja': loja_id}
            )
            context['pagamento_formset'] = FormaPagamentoEdicaoEspecialFormSet(
                instance=self.object
            )
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        produto_venda_formset = context['produto_venda_formset']
        pagamento_formset = context['pagamento_formset']

        loja = self.object.loja
        if not loja:
            messages.error(self.request, "Loja não encontrada na venda.")
            return self.form_invalid(form)

        if not Caixa.caixa_aberto(localtime(now()).date(), loja):
            messages.warning(self.request, 'Não é possível editar vendas com a loja bloqueada!')
            logger.warning("Tentativa de editar venda com caixa fechado para a loja %s", loja)
            return self.form_invalid(form)

        if not (form.is_valid() and produto_venda_formset.is_valid() and pagamento_formset.is_valid()):
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                self._atualizar_venda(form, loja)
                self._processar_produtos(produto_venda_formset, loja)
                self._processar_pagamentos(pagamento_formset, loja)
                messages.success(self.request, 'Venda atualizada com sucesso')
            return super().form_valid(form)
        except Exception as e:
            messages.error(self.request, f"Erro ao processar a venda: {str(e)}")
            logger.exception("Erro ao processar a venda: %s", e)
            return self.form_invalid(form)

    def _atualizar_venda(self, form, loja):
        form.instance.loja = loja
        form.instance.modificado_por = self.request.user
        self.object = form.save()

    def _processar_produtos(self, formset, loja):
        produtos_modificados = formset.save(commit=False)
        for produto_venda in produtos_modificados:
            produto_venda.venda = self.object
            produto_venda.loja = loja
            produto_venda.save()
        formset.save_m2m()

    def _processar_pagamentos(self, formset, loja):
        pagamentos_modificados = formset.save(commit=False)

        produto_venda = self.object.itens_venda.first()
        produto_base = produto_venda.produto if produto_venda else None
        quantidade_base = produto_venda.quantidade if produto_venda else 0

        entrada_base = None
        totais_parcelamento = {}
        if produto_base:
            entrada_base = produto_base.entrada_cliente * quantidade_base
            totais_parcelamento = {
                4: produto_base.valor_4_vezes * quantidade_base,
                6: produto_base.valor_6_vezes * quantidade_base,
                8: produto_base.valor_8_vezes * quantidade_base,
                10: produto_base.valor_10_vezes * quantidade_base,
            }

        for pagamento in pagamentos_modificados:
            pagamento.venda = self.object
            pagamento.loja = loja
            if pagamento.tipo_pagamento and pagamento.tipo_pagamento.nome.upper() == 'ENTRADA':
                if entrada_base is not None:
                    pagamento.valor = entrada_base
            else:
                try:
                    parcelas = int(pagamento.parcelas) if pagamento.parcelas else None
                except (TypeError, ValueError):
                    parcelas = None
                total = totais_parcelamento.get(parcelas)
                if total is not None:
                    pagamento.valor = total
            pagamento.save()

        formset.save_m2m()


class VendaDocumentosUpdateView(PermissionRequiredMixin, UpdateView):
    model = Venda
    form_class = VendaDocumentosForm
    template_name = 'venda/venda_documentos.html'
    permission_required = 'vendas.change_venda'
    
    def get_success_url(self):
        messages.success(self.request, 'Documentos atualizados com sucesso!')
        return reverse_lazy('vendas:venda_documentos', kwargs={'pk': self.object.pk})


class VendaDetailView(PermissionRequiredMixin, DetailView):
    model = Venda
    template_name = 'venda/venda_detail.html'
    permission_required = 'vendas.view_venda'
    
class VendaTrocarProdutoView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_venda'

    # quero um campo select com os produtos disponíveis para troca
    def get(self, request, pk):
        venda = get_object_or_404(Venda, pk=pk)
        loja = Loja.objects.get(id=venda.loja.id)

        produtos = ProdutoVenda.objects.filter(venda=venda)
        produtos_disponiveis = Estoque.objects.filter(loja=loja, quantidade_disponivel__gt=0)
        context = {
            'venda': venda,
            'produtos': produtos,
            'produtos_disponiveis': produtos_disponiveis,
            'loja': loja,
        }

        return render(request, 'venda/venda_trocar_produto.html', context)

    def post(self, request, pk):
        venda = get_object_or_404(Venda, pk=pk)
        self.venda_atual = venda  # Adicionar referência para validação
        produto_atual_id = request.POST.get('produto_atual')
        novo_produto_id = request.POST.get('novo_produto')
        imei_id = request.POST.get('imei')
        motivo_troca = request.POST.get('motivo')
        imei_obj = None
        if imei_id:
            try:
                imei_obj = EstoqueImei.objects.get(id=imei_id)
                imei = imei_obj.imei
            except EstoqueImei.DoesNotExist:
                imei = None
                messages.error(request, 'IMEI selecionado não encontrado.')
        else:
            imei = None
        loja = Loja.objects.get(id=request.session.get('loja_id'))

        if not produto_atual_id or not novo_produto_id or not imei:
            messages.error(request, 'Todos os campos são obrigatórios.')
            return redirect('vendas:venda_trocar_produto', pk=pk)

        try:
            produto_atual = ProdutoVenda.objects.get(id=produto_atual_id, venda=venda)
            novo_produto = Produto.objects.get(id=novo_produto_id)
            quantidade = produto_atual.quantidade

            produto_antigo_nome = produto_atual.produto.nome
            produto_antigo_imei = produto_atual.imei

            # Validações de estoque e IMEI removidas - não são mais necessárias

            # Atualiza ProdutoVenda
            produto_atual.produto = novo_produto
            produto_atual.imei = imei
            produto_atual.save(user=request.user)

            # Atualizações de estoque e IMEI removidas - não são mais necessárias
            
            data_atual = localtime(now()).date().strftime('%d/%m/%Y')
            hora_atual = localtime(now()).time().strftime('%H:%M')

            # atualiza venda marcando como is_trocado
            venda.is_trocado = True
            venda.observacao = (venda.observacao or "") + (
                f"\n{data_atual} {hora_atual} | Troca de produto:\n"
                f"- Usuário: {request.user.username}\n"
                f"- De: {produto_antigo_nome} - {produto_antigo_imei}\n"
                f"- Para: {novo_produto.nome} - {imei}\n"
                f"- Motivo: {motivo_troca}"
            )
            venda.save(user=request.user)

            messages.success(request, 'Produto trocado com sucesso!')
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            logger.exception("Erro ao trocar produto: %s", e)
            messages.error(request, "Erro ao trocar produto: %s" % e)

        return redirect('vendas:venda_detail', pk=pk)

    # Métodos de validação e restauração de estoque e IMEI removidos - não são mais necessários

def cancelar_venda(request, id):
    venda = get_object_or_404(Venda, id=id)
    data_atual = localtime(now()).date()

    if venda.is_deleted:
        messages.warning(request, 'Venda já cancelada')
        return redirect('vendas:venda_list')
    
    if not Caixa.caixa_aberto(localtime(now()).date(), Loja.objects.get(id=request.session.get('loja_id'))):
        messages.warning(request, 'Não é possível cancelar vendas com a loja bloqueada!')
        return redirect('vendas:venda_list')
    
    venda.is_deleted = True
    venda.save(user=request.user)
    messages.success(request, 'Venda cancelada com sucesso')
    return redirect('vendas:venda_list')

    
class CaixaTotalView(PermissionRequiredMixin, TemplateView):
    template_name = 'caixa/caixa_total.html'
    permission_required = 'vendas.view_caixa'
    
    def get_context_data(self, **kwargs):
        loja_id = self.request.session.get('loja_id')
        loja = Loja.objects.get(id=loja_id)

        caixas = Loja.objects.get(id=loja_id).caixa_loja.all().order_by('-data_abertura').filter(data_fechamento__isnull=False)
        vendas_caixa = []
        entradas_caixa = []
        saidas_caixa = []
        total_entrada = 0
        total_saida = 0
        total_venda =0

        for caixa in caixas:
            vendas = caixa.vendas.filter(is_deleted=False, pagamentos__tipo_pagamento__caixa=True)
            entradas = caixa.lancamentos_caixa.filter(tipo_lancamento='1')
            saidas = caixa.lancamentos_caixa.filter(tipo_lancamento='2')
            if vendas:
                vendas_caixa.append(vendas)

            if entradas:
                entradas_caixa.append(entradas)

            if saidas:
                saidas_caixa.append(saidas)
            
            total_entrada += caixa.entradas
            total_saida += caixa.saidas
            total_venda += caixa.saldo_total_dinheiro

        entradas_caixa_total = LancamentoCaixaTotal.objects.filter(tipo_lancamento='1', loja=loja)
        saidas_caixa_total = LancamentoCaixaTotal.objects.filter(tipo_lancamento='2', loja=loja)

        for entrada in entradas_caixa_total:
            total_entrada += entrada.valor

        for saida in saidas_caixa_total:
            total_saida += saida.valor

        entradas_caixa.append(entradas_caixa_total)
        saidas_caixa.append(saidas_caixa_total)

            
        total = (total_entrada + total_venda) - total_saida

        context = super().get_context_data(**kwargs)
        context['caixas'] = Caixa.objects.all()
        context['loja'] = Loja.objects.get(id=loja_id)
        context['vendas'] = vendas_caixa
        context['entradas'] = entradas_caixa
        context['saidas'] = saidas_caixa
        context['total_entrada'] = total_entrada
        context['total_saida'] = total_saida
        context['total_venda'] = total_venda
        context['total'] = total
        context['form_lancamento'] = LancamentoCaixaTotalForm()
        context['lancamentos'] = LancamentoCaixaTotal.objects.filter(loja=loja)
        
        return context
    
    def post(self, request, *args, **kwargs):
        loja_id = request.session.get('loja_id')
        loja = Loja.objects.get(id=loja_id)
        form = LancamentoCaixaTotalForm(request.POST)
        
        if form.is_valid():
            form.instance.loja = loja
            form.instance.criado_por = request.user
            form.save()
            messages.success(request, 'Lançamento realizado com sucesso')
            return redirect('vendas:caixa_total')
        
        messages.error(request, 'Erro ao realizar lançamento')
        return self.get(request, *args, **kwargs)
    

class LojaListView(BaseView, PermissionRequiredMixin, ListView):
    model = Loja
    template_name = 'loja/loja_list.html'
    context_object_name = 'lojas'
    permission_required = 'vendas.view_loja'

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
        # Adiciona as informações de repasses para cada loja no contexto
        for loja in context['lojas']:
            repasses, atrasados = loja.get_repasses_status()
            loja.repasses_info = {
                'repasses': repasses,
                'atrasados': atrasados
            }
        context['filter'] = self.request.GET.get('filter', '')  # Passa o filtro para o template
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
            print(form.errors)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(self.request, f"Erro no campo {field}: {error}")
        messages.error(self.request, 'Erro ao atualizar loja')
        return super().form_invalid(form)
    
    def get_success_url(self):
        return reverse_lazy('vendas:loja_detail', kwargs={'pk': self.object.id})

    
def replicar_qr_code_codigo_aplicativo(request, pk):
    loja = get_object_or_404(Loja, id=pk)
    if not loja.qr_code_aplicativo or loja.codigo_aplicativo is None:
        messages.error(request, '❌ Loja não possui QR Code ou código do aplicativo configurado.')
        return redirect('vendas:loja_list')

    lojas = Loja.objects.exclude(id=pk)
    for l in lojas:
        l.qr_code_aplicativo = loja.qr_code_aplicativo
        l.codigo_aplicativo = loja.codigo_aplicativo
        l.save()
    
    messages.success(request, '✅ QR Code e código do aplicativo replicados com sucesso para outras lojas.')
    return redirect('vendas:loja_list')

from django.db.models import Count, Sum
from django.utils.dateparse import parse_date

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



def product_information(request):
    product_id = request.GET.get('product_id')
    imei = request.GET.get('imei')
    product = get_object_or_404(Produto, id=product_id) if product_id else None
    imei_id = request.GET.get('imei_id')
    loja = get_object_or_404(Loja, id=request.session.get('loja_id'))
    
    if imei_id:
        product_imei = EstoqueImei.objects.get(id=imei_id, loja=loja)
        if product_imei.vendido:
            return JsonResponse({'status': 'error', 'message': 'IMEI já vendido'}, status=400)
        else:
            return JsonResponse({'status': 'success', 'product': product_imei.produto.nome, 'price': product_imei.produto_entrada.venda_unitaria})
    
    if imei and product:    
        try:
            product_imei = EstoqueImei.objects.filter(id=imei, produto=product, loja=loja).first()
            if product_imei.vendido:
                return JsonResponse({'status': 'error', 'message': 'IMEI já vendido'}, status=400)
            else:
                return JsonResponse({'status': 'success', 'product': product.nome, 'price': product_imei.produto_entrada.venda_unitaria})
        except EstoqueImei.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'IMEI não encontrado'}, status=404)
    elif product and not imei:
        estoque = Estoque.objects.filter(produto=product, loja=loja).first()
        if not estoque:
            return JsonResponse({'status': 'error', 'message': 'Estoque não encontrado'}, status=404)
        return JsonResponse({'status': 'success', 'product': product.nome, 'price': estoque.preco_medio()})

    

def get_payment_method(request):
    payment_id = request.GET.get('payment_id')
    payment = get_object_or_404(TipoPagamento, id=payment_id)
    
    if payment:
        return JsonResponse({
            'status': 'success',
            'parcela': payment.parcelas,
            'financeira': payment.financeira,
            'caixa': payment.caixa,
            'carne': payment.carne,
        })


class ProdutoAutoComplete(AutoResponseView):
    def get_queryset(self):
        return Produto.objects.all()
    
    
def get_produtos(request):
    loja_id = request.session.get('loja_id')
    term = request.GET.get('term')
    loja = get_object_or_404(Loja, id=loja_id)
    
    if term:
        produtos = Produto.objects.filter(estoque_atual__loja_id=loja_id, estoque_atual__quantidade_disponivel__gt=0, loja=loja).distinct().filter(nome__icontains=term)
    else:
        produtos = Produto.objects.filter(estoque_atual__loja_id=loja_id, estoque_atual__quantidade_disponivel__gt=0, loja=loja).distinct()

    produtos_data = [{'id': produto.id, 'text': produto.nome} for produto in produtos]
    return JsonResponse({'results': produtos_data})

class VendaPDFView(PermissionRequiredMixin, View):
    permission_required = 'vendas.view_venda'
    
    def get(self, request, pk):
        venda = get_object_or_404(Venda, id=pk)
        context = {
            'venda': venda,
            'produtos': venda.itens_venda.all(),
            'pagamentos': venda.pagamentos.all(),
        }
        return render(request, 'venda/venda_pdf.html', context)
    
    
class FolhaCaixaPDFView(PermissionRequiredMixin, View):
    permission_required = 'vendas.view_venda'
    
    def get(self, request, pk):
        caixa = get_object_or_404(Caixa, id=pk)
        vendas = caixa.vendas.filter(is_deleted=False)
        lancamentos = caixa.lancamentos_caixa.all()

        entrada_total = 0
        saida_total = 0

        for lancamento in lancamentos:
            if lancamento.tipo_lancamento == '1':
                entrada_total += lancamento.valor
            else:
                saida_total += lancamento.valor

        valor_venda_por_tipo_pagamento = {}

        for venda in vendas:
            for pagamento in venda.pagamentos.filter(tipo_pagamento__caixa=True):
                if not pagamento.tipo_pagamento.nao_contabilizar:
                    if pagamento.tipo_pagamento.nome not in valor_venda_por_tipo_pagamento:
                        valor_venda_por_tipo_pagamento[pagamento.tipo_pagamento.nome] = 0
                    valor_venda_por_tipo_pagamento[pagamento.tipo_pagamento.nome] += pagamento.valor

        caixa_valor_final = (caixa.saldo_total_dinheiro + caixa.entradas) - caixa.saidas
        valor_por_tipo_pagamento_total = sum(valor_venda_por_tipo_pagamento.values())

        entrada_total += valor_por_tipo_pagamento_total
        valor_final = entrada_total - saida_total
        saldo_total = entrada_total

        context = {
            'caixa': caixa,
            'data': localtime(now()).date(),
            'vendas': vendas,
            'lancamentos': lancamentos,
            'entrada_total': entrada_total,
            'saida_total': saida_total,
            'valor_por_tipo_pagamento_total': valor_por_tipo_pagamento_total,
            'saldo_total': saldo_total,
            'valor_venda_por_tipo_pagamento': valor_venda_por_tipo_pagamento.items(),
            'caixa_valor_final': caixa_valor_final,
            'valor_final': valor_final
        }
        return render(request, 'caixa/folha_caixa.html', context)

    
class FolhaProdutoPDFView(PermissionRequiredMixin, View):
    permission_required = 'vendas.view_venda'

    def get(self, request, pk):
        caixa = get_object_or_404(Caixa, id=pk)

        # Otimiza a query trazendo os relacionamentos necessários
        vendas = caixa.vendas.filter(is_deleted=False).prefetch_related(
            'itens_venda__produto', 'pagamentos'
        )

        produtos_info = []
        total_produtos = 0
        valor_total = 0

        for venda in vendas:
            # Captura todas as formas de pagamento únicas
            pagamentos = venda.pagamentos.all()
            formas_pagamento = ', '.join(set(p.tipo_pagamento.nome for p in pagamentos))
            valor_total += venda.pagamentos_valor_total_dinheiro
            total_custos = 0
            total_lucro = 0

            for produto in venda.itens_venda.all():
                if produto.produto and produto.produto.nome:
                    produtos_info.append({
                        'id_venda': venda.id,
                        'id_produto': produto.produto.id,
                        'produto': produto.produto.nome,
                        'vendedor': venda.vendedor.get_full_name() if venda.vendedor else 'N/A',
                        'preco': produto.valor_unitario,
                        'entrada_cliente': produto.produto.entrada_cliente,
                        'repasse_logista': produto.produto.valor_repasse_logista,
                        'quantidade': produto.quantidade,
                        'custo': produto.custo(),
                        'total': venda.pagamentos_valor_total,
                        'lucro': produto.lucro(),
                        'formas_pagamento': formas_pagamento
                    })
                    total_produtos += produto.quantidade

        total_lucro = sum(produto['lucro'] for produto in produtos_info)
        total_custos = sum(produto['custo'] for produto in produtos_info)

        context = {
            'caixa': caixa,
            'data': localtime(now()).date(),
            'produtos': produtos_info,
            'total_produtos': total_produtos,
            'valor_total': valor_total,
            'total_custos': total_custos,
            'total_lucro': total_lucro
        }

        return render(request, 'caixa/folha_produtos.html', context)


def gerar_qrcode_pix(chave, valor, txid, nome_loja, cidade_loja, descricao=None):
    pix = Pix()
    pix.set_pixkey(chave)
    pix.set_amount(valor)
    pix.set_txid(txid)
    pix.set_merchant_name(nome_loja[:25])
    pix.set_merchant_city(cidade_loja[:15])

    if descricao:
        pix.set_description(descricao[:30])

    payload = str(pix)
    print("Payload Pix:", payload)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def folha_carne_view(request, pk, tipo):
    venda = get_object_or_404(Venda, pk=pk)
    pagamento_carne = Pagamento.objects.filter(
        venda=venda,
        tipo_pagamento__carne=True
    ).first()

    if not pagamento_carne:
        messages.error(request, 'Venda não possui pagamento em carnê ou promissória')
        return redirect('vendas:venda_list')

    parcelas = pagamento_carne.parcelas_pagamento.all()
    cliente = venda.cliente
    loja = get_object_or_404(Loja, credfacil=True)

    parcelas_info = []
    for i, parcela in enumerate(parcelas):
        valor = f"{parcela.valor:.2f}"
        txid = f"{pagamento_carne.pk:04d}{i+1:02d}"
        descricao = f"{cliente.nome} - Parcela {i+1} de {len(parcelas)}"
        qr_base64 = gerar_qrcode_pix(
            chave=loja.chave_pix,
            valor=valor,
            txid=txid,
            nome_loja="CredFacil",
            cidade_loja="Belem",
            descricao=descricao
        )


        parcelas_info.append({
            'parcela': i + 1,
            'valor_parcela': valor,
            'data_vencimento': parcela.data_vencimento.strftime('%d/%m/%Y'),
            'qr_code_base64': qr_base64,
            'chave_pix': loja.chave_pix,
        })

    context = {
        'venda': venda,
        'valor_total': venda.pagamentos_valor_total,
        'tipo_pagamento': 'Carnê' if tipo == 'carne' else 'Promissória',
        'quantidade_parcelas': len(parcelas),
        'nome_cliente': cliente.nome.title(),
        'endereco_cliente': cliente.endereco,
        'cpf': cliente.cpf,
        'data_atual': localtime(now()).date(),
        'parcelas_info': parcelas_info,
        'loja': loja,
        'numero_loja': loja.telefone,
    }

    return render(request, "venda/folha_carne.html", context)


class RelatorioVendasView(PermissionRequiredMixin, FormView):
    template_name = 'relatorios/relatorio_vendas.html'
    form_class = RelatorioVendasForm
    permission_required = 'vendas.can_generate_report_sale'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['loja'] = self.request.session.get('loja_id')
        kwargs['user'] = self.request.user
        return kwargs

class RelatorioSolicitacoesView(PermissionRequiredMixin, FormView):
    template_name = 'relatorios/form_relatorio_solicitacao.html'
    form_class = RelatorioSolicitacoesForm
    permission_required = 'vendas.can_generate_report_sale'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['loja'] = self.request.session.get('loja_id')
        kwargs['user'] = self.request.user
        return kwargs
    
    
from datetime import datetime, timedelta

class FolhaRelatorioSolicitacoesView(PermissionRequiredMixin, TemplateView):
    template_name = 'relatorios/relatorio_solicitacoes.html'
    permission_required = 'vendas.can_generate_report_sale'

    def get(self, request, *args, **kwargs):
        # --- Extrai parâmetros ---
        data_inicial    = request.GET.get('data_inicial')
        data_final      = request.GET.get('data_final')
        produtos        = request.GET.getlist('produtos')
        vendedores      = request.GET.getlist('vendedores')
        loja_ids        = request.GET.getlist('lojas')
        status_solicitacao = request.GET.get('status_solicitacao')
        parcelas        = request.GET.get('parcelas')
        analise_serasa  = request.GET.get('analise_serasa')
        vr              = request.GET.get('venda_realizada', '').lower()
        analise_online  = request.GET.get('analise_online')

        filtros = {}
        user = request.user

        # status_solicitacao
        if status_solicitacao:
            filtros['analise_credito__status__in'] = status_solicitacao.split(',')

        # parcelas
        if parcelas:
            filtros['analise_credito__numero_parcelas__in'] = parcelas.split(',')

        # serasa
        if analise_serasa:
            filtros['comprovantes__restricao__in'] = analise_serasa.split(',')

        # venda realizada?
        if vr in ('true', '1'):
            filtros['analise_credito__venda__isnull'] = False
        elif vr in ('false', '0'):
            filtros['analise_credito__venda__isnull'] = True
            
        if analise_online in ('true', 'false', 'true', 'false'):
            filtros['analise_credito__is_online'] = analise_online == 'true'

        # datas
        if data_inicial and data_final:
            di = datetime.strptime(data_inicial, '%Y-%m-%d')
            df = datetime.strptime(data_final, '%Y-%m-%d') + timedelta(days=1)
            filtros['criado_em__range'] = [
                timezone.make_aware(di),
                timezone.make_aware(df),
            ]
        elif data_inicial:
            di = datetime.strptime(data_inicial, '%Y-%m-%d')
            filtros['criado_em__gte'] = timezone.make_aware(di)
        elif data_final:
            df = datetime.strptime(data_final, '%Y-%m-%d')
            filtros['criado_em__lte'] = timezone.make_aware(df)

        # outros filtros simples
        if vendedores:
            filtros['analise_credito__criado_por__in'] = vendedores
        if produtos:
            filtros['analise_credito__produto__in'] = produtos

        # Loja: se não selecionou, pega a loja do usuário logado
        if loja_ids:
            filtros['loja__id__in'] = loja_ids
            self.loja = Loja.objects.filter(pk__in=loja_ids).first()
        else:
            loja_id = request.session.get('loja_id')
            if request.user.has_perm('vendas.can_view_all_stores'):
                # Usuário pode ver todas as lojas e não selecionou nenhuma: pega todas
                all_lojas = Loja.objects.values_list('id', flat=True)
                filtros['loja__id__in'] = list(all_lojas)
                self.loja = None
            elif loja_id:
                filtros['loja__id'] = loja_id
                self.loja = Loja.objects.filter(pk=loja_id).first()
            else:
                self.loja = None

        # executa consulta
        qs = Cliente.objects.filter(**filtros).distinct()
        if not qs.exists():
            messages.warning(request, 'Nenhuma solicitação encontrada com os filtros informados')
            return redirect('vendas:form_solicitacao_relatorio')

        # pré-carrega vendas para calcular totais
        self.solicitacoes = qs.prefetch_related('vendas')
        self.total_vendas = self.solicitacoes.count()

        self.total_valor = sum(
            venda.valor_total_venda
            for cliente in self.solicitacoes
            for venda in cliente.vendas.all()
        )
        self.total_repasse = sum(
            venda.repasse_logista
            for cliente in self.solicitacoes
            for venda in cliente.vendas.all()
        )
        self.total_entrada = sum(
            venda.valor_entrada_cliente
            for cliente in self.solicitacoes
            for venda in cliente.vendas.all()
        )
        self.total_juros = sum(
            venda.juros
            for cliente in self.solicitacoes
            for venda in cliente.vendas.all()
        )

        # formata datas para exibição
        self.data_inicial_str = (
            datetime.strptime(data_inicial, '%Y-%m-%d').strftime('%d/%m/%Y')
            if data_inicial else None
        )
        if data_final:
            df_back = datetime.strptime(data_final, '%Y-%m-%d')
            self.data_final_str = df_back.strftime('%d/%m/%Y')
        else:
            self.data_final_str = None

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'solicitacoes': self.solicitacoes,
            'total_vendas': self.total_vendas,
            'total_valor':   self.total_valor,
            'total_entrada': self.total_entrada,
            'total_repasse': self.total_repasse,
            'total_juros':   self.total_juros,
            'data_inicial':  self.data_inicial_str,
            'data_final':    self.data_final_str,
            'lojas':         Loja.objects.filter(id__in=self.request.GET.getlist('lojas')) if self.loja else Loja.objects.all(),
        })
        return ctx



class FolhaRelatorioVendasView(PermissionRequiredMixin, TemplateView):
    template_name = 'relatorios/folha_relatorio_vendas.html'
    permission_required = 'vendas.can_generate_report_sale'

    def get(self, request, *args, **kwargs):
        # --- montamos filtros exatamente como antes ---
        data_inicial = request.GET.get('data_inicial')
        data_final = request.GET.get('data_final')
        produtos = request.GET.getlist('produtos')
        vendedores = request.GET.getlist('vendedores')
        analise_serasa = request.GET.getlist('analise_serasa')
        parcelas = request.GET.getlist('parcelas')
        loja_ids = request.GET.getlist('lojas')
        analise_online = request.GET.get('analise_online')

        filtros = {}

        # datas
        if data_inicial and data_final:
            di = datetime.strptime(data_inicial, '%Y-%m-%d')
            df = datetime.strptime(data_final, '%Y-%m-%d') + timedelta(days=1)
            filtros['data_venda__range'] = [
                timezone.make_aware(di),
                timezone.make_aware(df),
            ]
        elif data_inicial:
            di = datetime.strptime(data_inicial, '%Y-%m-%d')
            filtros['data_venda__gte'] = timezone.make_aware(di)
        elif data_final:
            df = datetime.strptime(data_final, '%Y-%m-%d')
            filtros['data_venda__lte'] = timezone.make_aware(df)

        # outros filtros simples
        if vendedores:
            filtros['vendedor__in'] = vendedores
        if analise_serasa:
            filtros['cliente__comprovantes__restricao__in'] = analise_serasa
        if parcelas:
            filtros['analises_credito_venda__numero_parcelas__in'] = parcelas
        if produtos:
            filtros['produtos__in'] = produtos

        # Loja: se não selecionou, pega a loja do usuário logado
        if loja_ids:
            filtros['loja__id__in'] = loja_ids
            self.loja = Loja.objects.filter(pk__in=loja_ids).first()
        else:
            loja_id = request.session.get('loja_id')
            if request.user.has_perm('vendas.can_view_all_stores'):
                # Usuário pode ver todas as lojas e não selecionou nenhuma: pega todas
                all_lojas = Loja.objects.values_list('id', flat=True)
                filtros['loja__id__in'] = list(all_lojas)
                self.loja = None
            elif loja_id:
                filtros['loja__id'] = loja_id
                self.loja = Loja.objects.filter(pk=loja_id).first()
            else:
                self.loja = None
        
        if analise_online in ('true', 'false', 'true', 'false'):
            filtros['analises_credito_venda__is_online'] = analise_online == 'true'

        # faz a query
        self.vendas = Venda.objects.filter(**filtros).distinct()

        # se não encontrou, redireciona antes de chamar get_context_data
        if not self.vendas.exists():
            messages.warning(request, 'Nenhuma venda encontrada com os filtros informados')
            return redirect('vendas:venda_relatorio')

        # pré-calcula totais para usar no contexto
        self.total_vendas = self.vendas.count()
        self.total_juros = sum(v.juros for v in self.vendas)
        self.total_valor = sum(v.valor_total_venda for v in self.vendas)
        self.total_entrada = sum(v.valor_entrada_cliente for v in self.vendas)
        self.total_repasse = sum(v.repasse_logista for v in self.vendas)

        # guarda strings formatadas
        self.data_inicial_str = datetime.strptime(data_inicial, '%Y-%m-%d').strftime("%d/%m/%Y") if data_inicial else None
        if data_final:
            df_back = datetime.strptime(data_final, '%Y-%m-%d')
            self.data_final_str = df_back.strftime("%d/%m/%Y")
        else:
            self.data_final_str = None

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'vendas': self.vendas,
            'total_vendas': self.total_vendas,
            'total_juros': self.total_juros,
            'total_valor': self.total_valor,
            'total_entrada': self.total_entrada,
            'total_repasse': self.total_repasse,
            'data_inicial': self.data_inicial_str,
            'data_final': self.data_final_str,
            'lojas': Loja.objects.filter(id__in=self.request.GET.getlist('lojas')) if self.loja else Loja.objects.all(),
        })
        return context
   
   
    
class ProdutoVendidoListView(PermissionRequiredMixin, ListView):
    model = ProdutoVenda
    template_name = 'produto_vendido/produto_vendido_list.html'
    context_object_name = 'produtos_vendidos'
    permission_required = 'vendas.view_produtovenda'
    paginate_by = 10
    
    def get_queryset(self):
        query = super().get_queryset()
        user = self.request.user
        nome = self.request.GET.get('nome')
        imei = self.request.GET.get('imei')
        cpf = self.request.GET.get('cpf')
        data = self.request.GET.get('data')
        data_fim = self.request.GET.get('data_fim')
        loja = self.request.GET.get('loja')
        
        if loja and user.has_perm('vendas.can_view_all_products_sold'):
            loja_id = loja
        elif user.has_perm('vendas.can_view_all_products_sold'):
            loja_id = None
        else:
            loja_id = self.request.session.get('loja_id')
            
        if loja_id:
            loja = Loja.objects.get(id=loja_id)

        if nome:
            query = query.filter(produto__nome__icontains=nome)
        if imei:
            query = query.filter(imei__icontains=imei)
        if cpf:
            query = query.filter(venda__cliente__cpf__icontains=cpf)
        if data and data_fim:
            query = query.filter(venda__data_venda__range=[data, data_fim])
        if loja:
            query = query.filter(venda__loja=loja)
        
        return query.order_by('-venda__data_venda')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['nome'] = self.request.GET.get('nome')
        context['imei'] = self.request.GET.get('imei')
        context['cpf'] = self.request.GET.get('cpf')
        context['data'] = self.request.GET.get('data')
        context['data_fim'] = self.request.GET.get('data_fim')
        context['loja'] = self.request.GET.get('loja')
        
        context['lojas'] = Loja.objects.all()
        return context


def contrato_view(request, pk):
    
    # Busca a venda
    venda = Venda.objects.get(pk=pk)
    valor_total = venda.pagamentos_valor_total
    pagamento_carne = Pagamento.objects.filter(venda=venda, tipo_pagamento__carne=True).first()
    aparelho = venda.itens_venda.first()
    imei = aparelho.imei if aparelho else None
    loja = Loja.objects.get(id=request.session.get('loja_id'))
    cliente = venda.cliente
    contrato = loja.contrato
    contrato = json.dumps(contrato)
    primeira_parcela = pagamento_carne.data_primeira_parcela if pagamento_carne else None
    parcelas = pagamento_carne.parcelas if pagamento_carne else 0
    parcelas_meses = []

    for i in range(parcelas):
        # somar 1 meses a data de vencimento
        mes = primeira_parcela.month + i
        ano = primeira_parcela.year
        if mes > 12:
            mes -= 12
            ano += 1
        data_vencimento = primeira_parcela.replace(month=mes, year=ano)
        parcelas_meses.append(data_vencimento.strftime('%d/%m/%Y'))

    ultima_parcela = parcelas_meses[-1] if parcelas_meses else None

    context = {
        'venda': venda,
        'valor_total': valor_total,
        'tipo_pagamento': 'Carnê' if pagamento_carne else 'À vista',
        'cliente': cliente,
        'data_atual': localtime(now()).date(),
        'loja': loja,
        'contrato': contrato,
        'aparelho': aparelho,
        'imei': imei,
        'valor_parcela': pagamento_carne.valor_parcela if pagamento_carne else None,
        'quantidade_parcelas': parcelas,
        'parcelas_meses': parcelas_meses,
        'primeira_parcela': primeira_parcela.strftime('%d/%m/%Y') if primeira_parcela else None,
        'ultima_parcela': ultima_parcela,

    }

    return render(request, "venda/contrato.html", context)



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

class ConsultaPagamentosView(FormView):
    template_name = "publico/consulta_pagamentos.html"
    form_class = ClienteConsultaForm

    def form_valid(self, form):
        cpf = form.cleaned_data['cpf']
        dob = form.cleaned_data['date_of_birth']
        pagamentos = (
            Pagamento.objects
            .with_status_flags()
            .filter(
                venda__cliente__cpf=cpf,
                venda__cliente__nascimento=dob
            )
        )
        return self.render_to_response(
            self.get_context_data(form=form, pagamentos=pagamentos)
        )
        

class PagamentoDetailView(DetailView):
    model = Pagamento
    template_name = 'publico/pagamento_detail.html'
    context_object_name = 'pagamento'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        ctx       = super().get_context_data(**kwargs)
        pagamento = ctx['pagamento']
        
        # cálculo do desconto
        restantes = pagamento.parcelas_pagamento.filter(pago=False)
        total_restante    = sum(p.valor for p in restantes)
        discount_pct      = getattr(pagamento, 'porcentagem_desconto', Decimal('0'))
        discount_amount   = (total_restante * discount_pct / Decimal('100')).quantize(Decimal('0.01'))
        total_com_desconto= (total_restante - discount_amount).quantize(Decimal('0.01'))

        confirmando_count = pagamento.parcelas_pagamento.filter(
            pagamento_efetuado=True,
            pago=False
        ).count()

        # dados da loja
        loja   = get_object_or_404(Loja, credfacil=True)
        chave  = loja.chave_pix
        cidade = "Belem"

        qr_items = []
        for parcela in pagamento.parcelas_pagamento.all().order_by('numero_parcela'):
            if not parcela.pago:
                txid   = f"{pagamento.pk:04d}{parcela.numero_parcela:02d}"
                valor  = f"{parcela.valor:.2f}"
                descricao = f"Parcela {parcela.numero_parcela} - Pagamento {pagamento.pk}"

                qr_b64 = gerar_qrcode_pix(
                    chave=chave,
                    valor=valor,
                    txid=txid,
                    nome_loja='credfacil',
                    cidade_loja=cidade,
                    descricao=descricao
                )
            else:
                qr_b64 = None

            qr_items.append({
                'parcela': parcela,
                'qr_b64': qr_b64,
            })

        # QR para quitação total com desconto
        if restantes:
            txid_qt = f"{pagamento.pk:04d}QT"
            valor_qt = f"{total_com_desconto:.2f}"
            descricao_qt = f"Quitacao total - Pagamento {pagamento.pk}"

            discount_qr_b64 = gerar_qrcode_pix(
                chave=chave,
                valor=valor_qt,
                txid=txid_qt,
                nome_loja='credfacil',
                cidade_loja=cidade,
                descricao=descricao_qt
            )
        else:
            discount_qr_b64 = None

        ctx.update({
            'qr_items': qr_items,
            'restantes_count': restantes.count(),
            'total_restante': total_restante,
            'confirmando_count': confirmando_count,
            'discount_pct': discount_pct,
            'total_com_desconto': total_com_desconto,
            'discount_qr_b64': discount_qr_b64,
            'loja': loja,
        })
        return ctx

class InformarPagamentoView(View):
    def post(self, request, pk):
        parcela = get_object_or_404(Parcela, pk=pk)
        parcela.pagamento_efetuado = True
        parcela.pagamento_efetuado_em = timezone.now()
        parcela.data_pagamento = timezone.now().date()
        parcela.save(update_fields=['pagamento_efetuado', 'data_pagamento'])
        messages.success(request, "Pagamento informado e está em confirmação.")
        return redirect('vendas:pagamento_detail', pk=parcela.pagamento.pk)


# vendas/views.py

class InformarTodosPagamentosView(View):
    """
    View para o CLIENTE. Apenas informa que o pagamento foi efetuado,
    sem alterar valores ou confirmar o pagamento.
    """
    def post(self, request, pk):
        pagamento = get_object_or_404(Pagamento, pk=pk)
        
        # Pega todas as parcelas que ainda não foram informadas nem pagas
        parcelas_a_informar = pagamento.parcelas_pagamento.filter(
            pagamento_efetuado=False, 
            pago=False
        )
        
        # Atualiza todas de uma vez (bulk update)
        updated_count = parcelas_a_informar.update(
            pagamento_efetuado=True,
            pagamento_efetuado_em=timezone.now()
        )

        if updated_count > 0:
            messages.success(
                request,
                f"{updated_count} parcelas foram informadas para quitação e agora aguardam a confirmação do nosso time."
            )
        else:
            messages.warning(request, "Nenhuma parcela nova para informar.")

        return redirect('vendas:pagamento_detail', pk=pagamento.pk)



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

        except Exception as e:
            messages.error(request, f"Ocorreu um erro ao confirmar a quitação: {e}")

        return redirect('financeiro:contas_a_receber_update', pk=pagamento.pk)    
    
    
class GuiaView(LoginRequiredMixin, TemplateView):
    template_name = 'guia.html'


class GraficoTemplateView(TemplateView):
    template_name = 'dash/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_get = self.request.GET.get('loja')
        loja = Loja.objects.filter(id=loja_get) if loja_get else Loja.objects.all()

        vendas = Venda.objects.filter(is_deleted=False, loja__in=loja)
        parcelas_qs = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX'
        ).select_related('pagamento', 'pagamento__venda')

        parcelas_por_venda = defaultdict(list)

        for parcela in parcelas_qs:
            parcelas_por_venda[parcela.pagamento.venda_id].append(parcela)

        total_vendas = vendas.count()
        total_de_parcelas_vencidas = total_de_parcelas_pagas = total_de_parcelas_a_vencer = 0
        total_pagas = total_vencidas = total_a_vencer = total_geral_parcelas = 0

        valores_por_loja = defaultdict(lambda: {
            'total_pagas': 0, 'total_vencidas': 0, 'total_a_vencer': 0,
            'total_desativados_vencidas': 0, 'total_desativados_a_vencer': 0,
        })

        # --- DASH POR MÊS ---
        # Estrutura: {loja_nome: {YYYY-MM: {'pago': x, 'vencido': y, 'a_vencer': z}}}
        dash_mensal_lojas = defaultdict(lambda: defaultdict(lambda: {'pago': 0, 'vencido': 0, 'a_vencer': 0}))

        for venda in vendas:
            loja_nome = venda.loja.nome if venda.loja else 'Desconhecida'
            parcelas = parcelas_por_venda.get(venda.id, [])

            # Em devolução: manter pagas; ignorar futuras (vencidas/a vencer)
            parcelas_vencidas = [
                p for p in parcelas
                if p.data_vencimento < timezone.now().date()
                and not p.pago
                and not p.pagamento_efetuado
                and not p.pagamento.devolucao
            ]
            parcelas_pagas = [p for p in parcelas if p.pago and not p.pagamento_efetuado]
            parcelas_a_vencer = [
                p for p in parcelas
                if p.data_vencimento >= timezone.now().date()
                and not p.pago
                and not p.pagamento_efetuado
                and not p.pagamento.devolucao
            ]

            total_geral_parcelas += len(parcelas)
            qtd_vencidas, qtd_pagas, qtd_a_vencer = len(parcelas_vencidas), len(parcelas_pagas), len(parcelas_a_vencer)

            total_de_parcelas_vencidas += qtd_vencidas
            total_de_parcelas_pagas += qtd_pagas
            total_de_parcelas_a_vencer += qtd_a_vencer

            valor_vencidas = sum(p.valor for p in parcelas_vencidas)
            valor_pagas = sum(p.valor for p in parcelas_pagas)
            valor_a_vencer = sum(p.valor for p in parcelas_a_vencer)

            total_vencidas += valor_vencidas
            total_pagas += valor_pagas
            total_a_vencer += valor_a_vencer

            valores_por_loja[loja_nome]['total_a_vencer'] += valor_a_vencer
            valores_por_loja[loja_nome]['total_vencidas'] += valor_vencidas
            valores_por_loja[loja_nome]['total_pagas'] += valor_pagas

            # Calcular desativados por loja
            parcelas_desativadas_loja = Parcela.objects.filter(
                pagamento__venda=venda,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__desativado=True,
                pago=False
            )

            for parcela_desativada in parcelas_desativadas_loja:
                if parcela_desativada.data_vencimento < timezone.now().date():
                    valores_por_loja[loja_nome]['total_desativados_vencidas'] += parcela_desativada.valor
                else:
                    valores_por_loja[loja_nome]['total_desativados_a_vencer'] += parcela_desativada.valor

            # DASH MENSAL: soma por mês/ano
            for p in parcelas:
                mes_ano = p.data_vencimento.strftime('%Y-%m')
                if p.pago and not p.pagamento_efetuado:
                    dash_mensal_lojas[loja_nome][mes_ano]['pago'] += float(p.valor)
                elif (
                    p.data_vencimento < timezone.now().date()
                    and not p.pago
                    and not p.pagamento_efetuado
                    and not p.pagamento.devolucao
                ):
                    dash_mensal_lojas[loja_nome][mes_ano]['vencido'] += float(p.valor)
                elif (
                    p.data_vencimento >= timezone.now().date()
                    and not p.pago
                    and not p.pagamento_efetuado
                    and not p.pagamento.devolucao
                ):
                    dash_mensal_lojas[loja_nome][mes_ano]['a_vencer'] += float(p.valor)

        for loja_nome, valores in valores_por_loja.items():
            total_geral = valores['total_pagas'] + valores['total_vencidas'] + valores['total_a_vencer'] + valores['total_desativados_vencidas'] + valores['total_desativados_a_vencer']
            valores['pct_pagas'] = round((valores['total_pagas'] / total_geral) * 100, 2) if total_geral else 0
            valores['pct_vencidas'] = round((valores['total_vencidas'] / total_geral) * 100, 2) if total_geral else 0
            valores['pct_desativados'] = round(((valores['total_desativados_vencidas'] + valores['total_desativados_a_vencer']) / total_geral) * 100, 2) if total_geral else 0

        # Prepara dash mensal para o template (serializável)
        dash_mensal_json = {}
        for loja_nome, meses in dash_mensal_lojas.items():
            dash_mensal_json[loja_nome] = []
            for mes_ano in sorted(meses.keys()):
                dash_mensal_json[loja_nome].append({
                    'mes': mes_ano,
                    'pago': meses[mes_ano]['pago'],
                    'vencido': meses[mes_ano]['vencido'],
                    'a_vencer': meses[mes_ano]['a_vencer'],
                })

        # --- CÁLCULO DOS CLIENTES DESATIVADOS ---
        total_desativados_vencidas = 0
        total_desativados_a_vencer = 0
        qtd_desativados_vencidas = 0
        qtd_desativados_a_vencer = 0

        # Busca parcelas de clientes desativados (apenas não pagas)
        parcelas_desativadas = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX',
            pagamento__desativado=True,
            pago=False  # Apenas parcelas não pagas
        )

        for parcela in parcelas_desativadas:
            if parcela.data_vencimento < timezone.now().date():
                total_desativados_vencidas += parcela.valor
                qtd_desativados_vencidas += 1
            else:
                total_desativados_a_vencer += parcela.valor
                qtd_desativados_a_vencer += 1

        # Total de pagamentos desativados
        total_pagamentos_desativados = Pagamento.objects.filter(
            venda__in=vendas,
            tipo_pagamento__nome='IPX',
            desativado=True
        ).count()

        # --- CÁLCULO DO VALOR TOTAL DE REPASSES ---
        total_repasses = 0
        repasses_por_loja = defaultdict(lambda: 0)
        
        # Buscar todos os produtos vendidos das vendas filtradas
        produtos_vendidos = ProdutoVenda.objects.filter(
            venda__in=vendas
        ).select_related('produto', 'venda__loja')
        
        for produto_venda in produtos_vendidos:
            valor_repasse = produto_venda.produto.valor_repasse_logista or 0
            total_repasses += valor_repasse
            loja_nome = produto_venda.venda.loja.nome if produto_venda.venda.loja else 'Desconhecida'
            repasses_por_loja[loja_nome] += valor_repasse

        context.update({
            'loja_get': int(loja_get) if loja_get else None,
            'lojas': Loja.objects.all(),
            'total_vendas_loja': total_vendas,
            'total_de_parcelas_geral': total_geral_parcelas,
            'parcelas_vencidas': total_de_parcelas_vencidas,
            'parcelas_pagas': total_de_parcelas_pagas,
            'parcelas_a_vencer': total_de_parcelas_a_vencer,
            'valor_total_parcelas': total_pagas + total_vencidas + total_a_vencer,
            'total_pagas': total_pagas,
            'total_vencidas': total_vencidas,
            'total_a_vencer': total_a_vencer,
            'total_desativados_vencidas': total_desativados_vencidas,
            'total_desativados_a_vencer': total_desativados_a_vencer,
            'qtd_desativados_vencidas': qtd_desativados_vencidas,
            'qtd_desativados_a_vencer': qtd_desativados_a_vencer,
            'total_pagamentos_desativados': total_pagamentos_desativados,
            'total_repasses': total_repasses,
            'repasses_por_loja': dict(repasses_por_loja),
            'dados_lojas': json.dumps(valores_por_loja, default=str),
            'dash_mensal_lojas': json.dumps(dash_mensal_json, default=str) if loja_get else None,
        })

        return context

@permission_required('vendas.change_analisecreditocliente', raise_exception=True)
def informar_imei_analise(request, pk):
    """View para analista informar o IMEI na análise de crédito"""
    # Verificar se o usuário é analista
    if not request.user.groups.filter(name='ANALISTA').exists():
        messages.error(request, 'Apenas analistas podem informar o IMEI.')
        return redirect('vendas:cliente_list')
    """View para informar o IMEI na análise de crédito antes de gerar a venda"""
    analise = get_object_or_404(AnaliseCreditoCliente, pk=pk)
    
    # Verificar se o status está correto para informar IMEI
    # Para iPhone: verificar se o iCloud foi confirmado pelo analista
    # Para Android: verificar se o aplicativo foi confirmado pelo vendedor
    if analise.produto.is_iphone:
        if not analise.icloud_confirmado_analista:
            messages.error(request, 'Só é possível informar IMEI após confirmar a configuração do iCloud.')
            return redirect('vendas:cliente_list')
    else:
        if analise.status_aplicativo != 'C':
            messages.error(request, 'Só é possível informar IMEI após o vendedor confirmar a instalação do aplicativo.')
            return redirect('vendas:cliente_list')
    
    if request.method == 'POST':
        imei_informado = request.POST.get('imei_informado')
        
        if not imei_informado:
            messages.error(request, 'IMEI é obrigatório.')
            return redirect('vendas:cliente_update', pk=analise.cliente.pk)
        
        # Verificar se o IMEI já existe no estoque
        loja = get_object_or_404(Loja, id=request.session.get('loja_id'))
        estoque_imei_existente = EstoqueImei.objects.filter(
            imei=imei_informado,
            produto=analise.produto,
            loja=loja,
            vendido=False,
            cancelado=False
        ).first()
        
        if estoque_imei_existente:
            # IMEI já existe no estoque
            analise.imei = estoque_imei_existente
            analise.imei_informado = imei_informado
            analise.save()
            messages.success(request, f'IMEI {imei_informado} associado com sucesso à análise.')
        else:
            # IMEI não existe, criar novo registro no estoque
            try:
                # Criar novo registro no EstoqueImei
                novo_estoque_imei = EstoqueImei(
                    produto=analise.produto,
                    imei=imei_informado,
                    loja=loja,
                    vendido=False,
                    aplicativo_instalado=False,
                    cancelado=False
                )
                # Salvar com o usuário para preencher criado_por
                novo_estoque_imei.save(user=request.user)
                
                # Associar à análise
                analise.imei = novo_estoque_imei
                analise.imei_informado = imei_informado
                analise.save()
                
                messages.success(request, f'IMEI {imei_informado} criado e associado com sucesso à análise.')
            except Exception as e:
                messages.error(request, f'Erro ao criar IMEI: {str(e)}')
                return redirect('vendas:cliente_update', pk=analise.cliente.pk)
        
        # Marcar aplicativo como instalado quando o analista informar o IMEI (apenas para Android)
        if not analise.produto.is_iphone:
            analise.status_aplicativo = 'I'
            analise.save()
        messages.success(request, 'IMEI informado com sucesso! Venda liberada para geração pelo vendedor.')
        
        # Enviar notificação para analistas e administradores
        from notifications.signals import notify
        from notificacao.utils import enviar_ws_para_usuario
        
        cliente_nome = analise.cliente.nome if analise.cliente else "Cliente"
        imei_info = f'Imei {imei_informado}' if imei_informado else 'IMEI não informado'
        
        verb = f'Analista informou IMEI para cliente {cliente_nome.capitalize()}.'
        description = f'{imei_info} da loja {loja.nome.capitalize()}. Venda liberada para geração pelo vendedor.'
        
        # Notificar analistas e administradores
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['ADMINISTRADOR', 'ANALISTA']).exclude(id=request.user.id)
        )
        
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=analise.cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=analise.cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )
        
        return redirect('vendas:cliente_list')
    
    # GET request - mostrar formulário
    context = {
        'analise': analise,
        'cliente': analise.cliente,
    }
    return render(request, 'vendas/informar_imei_analise.html', context)

class AnalistaConfirmInstalledView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_status_analise'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        analise_credito = cliente.analise_credito
        
        # Verificar se o usuário é analista
        if not request.user.groups.filter(name='ANALISTA').exists():
            messages.error(request, 'Apenas analistas podem confirmar a instalação.')
            return redirect('vendas:cliente_list')
        
        # Verificar se o IMEI está informado
        if not analise_credito.imei:
            messages.error(request, 'IMEI deve estar informado para confirmar a instalação.')
            return redirect('vendas:cliente_list')
        
        # Verificar se o status está correto
        if analise_credito.status_aplicativo != 'C':
            messages.error(request, 'Status do aplicativo deve estar "Aguardando Confirmação" para confirmar a instalação.')
            return redirect('vendas:cliente_list')
        
        # Marcar como instalado
        analise_credito.status_aplicativo = 'I'
        analise_credito.save()
        
        # Enviar notificação para vendedores
        from notifications.signals import notify
        from notificacao.utils import enviar_ws_para_usuario
        
        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        
        verb = f'Analista confirmou instalação do app para cliente {cliente_nome.capitalize()}.'
        description = f'IMEI {analise_credito.imei.imei} da loja {loja.nome.capitalize()}. Venda liberada para geração.'
        
        # Notificar vendedores e outros analistas
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['VENDEDOR', 'ADMINISTRADOR', 'ANALISTA']).exclude(id=request.user.id)
        )
        
        for user in usuarios_para_notificar:
            notify.send(
                analise_credito,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise_credito,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )
        
        messages.success(request, "✅ Instalação confirmada pelo analista! Venda liberada para geração.")
        return redirect('vendas:cliente_list')


class ClienteConfigurarIcloudView(PermissionRequiredMixin, View):
    """Vendedor confirma que configurou o iCloud no iPhone"""
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        analise = cliente.analise_credito
        
        if not analise.email_icloud or not analise.senha_icloud:
            messages.error(request, '❌ Email e senha iCloud não configurados pela análise.')
            return redirect('vendas:cliente_list')
        
        analise.icloud_configurado_vendedor = True
        analise.save()
        
        # Enviar notificação para analistas
        from notifications.signals import notify
        from notificacao.utils import enviar_ws_para_usuario
        
        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        
        verb = f'Vendedor configurou iCloud para cliente {cliente_nome.capitalize()}'
        description = f'iPhone da loja {loja.nome.capitalize()}. Aguardando confirmação do analista.'
        
        # Notificar analistas
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['ANALISTA', 'ADMINISTRADOR']).exclude(id=request.user.id)
        )
        
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )
        
        messages.success(request, f'✅ Configuração iCloud confirmada para {cliente.nome}')
        return redirect('vendas:cliente_list')


class AnalistaConfirmIcloudView(PermissionRequiredMixin, View):
    """Analista confirma que o iCloud foi configurado corretamente"""
    permission_required = 'vendas.change_status_analise'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        analise = cliente.analise_credito
        
        # Verificar se o usuário é analista
        if not request.user.groups.filter(name='ANALISTA').exists():
            messages.error(request, 'Apenas analistas podem confirmar a configuração do iCloud.')
            return redirect('vendas:cliente_list')
        
        if not analise.icloud_configurado_vendedor:
            messages.error(request, '❌ Vendedor ainda não confirmou a configuração do iCloud.')
            return redirect('vendas:cliente_list')
        
        analise.icloud_confirmado_analista = True
        analise.save()
        
        # Enviar notificação para vendedores
        from notifications.signals import notify
        from notificacao.utils import enviar_ws_para_usuario
        
        cliente_nome = cliente.nome if cliente else "Cliente"
        loja = cliente.loja
        
        verb = f'Analista confirmou configuração iCloud para cliente {cliente_nome.capitalize()}'
        description = f'iPhone da loja {loja.nome.capitalize()}. Aguardando IMEI para gerar venda.'
        
        # Notificar vendedores e outros analistas
        usuarios_para_notificar = list(
            User.objects.filter(groups__name__in=['VENDEDOR', 'ADMINISTRADOR', 'ANALISTA']).exclude(id=request.user.id)
        )
        
        for user in usuarios_para_notificar:
            notify.send(
                analise,
                recipient=user,
                verb=verb,
                description=description,
                target=cliente,
            )

            # WebSocket
            ultima_notificacao = user.notifications.unread().order_by('-timestamp').first()
            if ultima_notificacao:
                enviar_ws_para_usuario(
                    usuario=user,
                    instance=analise,
                    notification_id=ultima_notificacao.id,
                    verb=verb,
                    description=description,
                    target_url=cliente.get_absolute_url(),
                    type_notification='analise_credito_cliente',
                )
        
        messages.success(request, f'✅ Configuração iCloud confirmada pelo analista para {cliente.nome}')
        return redirect('vendas:cliente_list')


class DashboardReportPDFView(PermissionRequiredMixin, View):
    permission_required = 'vendas.can_generate_dashboard_report'
    
    def get(self, request, *args, **kwargs):
        # Reutilizar a lógica da GraficoTemplateView para calcular os dados
        context = self.get_dashboard_data()
        
        # Renderizar o template PDF
        template = get_template('dash/relatorio_pdf.html')
        html = template.render(context)
        
        # Gerar PDF
        pdf_buffer = BytesIO()
        weasyprint.HTML(string=html).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        
        # Retornar o PDF
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="relatorio_dashboard_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        return response
    
    def get_dashboard_data(self):
        """Reutiliza a lógica da GraficoTemplateView para calcular os dados"""
        # Buscar todas as lojas
        lojas = Loja.objects.all()
        
        vendas = Venda.objects.filter(is_deleted=False)
        parcelas_qs = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX'
        ).select_related('pagamento', 'pagamento__venda')

        parcelas_por_venda = defaultdict(list)
        for parcela in parcelas_qs:
            parcelas_por_venda[parcela.pagamento.venda_id].append(parcela)

        # Dados por loja
        dados_por_loja = {}
        
        for loja in lojas:
            vendas_loja = vendas.filter(loja=loja)
            parcelas_loja = Parcela.objects.filter(
                pagamento__venda__in=vendas_loja,
                pagamento__tipo_pagamento__nome='IPX'
            ).select_related('pagamento', 'pagamento__venda')

            # Calcular KPIs para esta loja
            total_vendas_loja = vendas_loja.count()
            total_de_parcelas_vencidas = total_de_parcelas_pagas = total_de_parcelas_a_vencer = 0
            total_pagas = total_vencidas = total_a_vencer = 0

            for venda in vendas_loja:
                parcelas = parcelas_por_venda.get(venda.id, [])
                
                parcelas_vencidas = [p for p in parcelas if p.data_vencimento < timezone.now().date() and not p.pago and not p.pagamento_efetuado]
                parcelas_pagas = [p for p in parcelas if p.pago and not p.pagamento_efetuado]
                parcelas_a_vencer = [p for p in parcelas if p.data_vencimento >= timezone.now().date() and not p.pago and not p.pagamento_efetuado]

                total_de_parcelas_vencidas += len(parcelas_vencidas)
                total_de_parcelas_pagas += len(parcelas_pagas)
                total_de_parcelas_a_vencer += len(parcelas_a_vencer)

                total_vencidas += sum(p.valor for p in parcelas_vencidas)
                total_pagas += sum(p.valor for p in parcelas_pagas)
                total_a_vencer += sum(p.valor for p in parcelas_a_vencer)

            # Calcular desativados para esta loja
            parcelas_desativadas = Parcela.objects.filter(
                pagamento__venda__in=vendas_loja,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__desativado=True,
                pago=False
            )
            
            total_desativados_vencidas = sum(p.valor for p in parcelas_desativadas if p.data_vencimento < timezone.now().date())
            total_desativados_a_vencer = sum(p.valor for p in parcelas_desativadas if p.data_vencimento >= timezone.now().date())
            qtd_desativados_vencidas = sum(1 for p in parcelas_desativadas if p.data_vencimento < timezone.now().date())
            qtd_desativados_a_vencer = sum(1 for p in parcelas_desativadas if p.data_vencimento >= timezone.now().date())

            # Calcular repasses para esta loja
            produtos_vendidos = ProdutoVenda.objects.filter(venda__in=vendas_loja)
            total_repasses = sum(pv.produto.valor_repasse_logista or 0 for pv in produtos_vendidos)

            # Valor total das parcelas
            valor_total_parcelas = total_pagas + total_vencidas + total_a_vencer + total_desativados_vencidas + total_desativados_a_vencer

            dados_por_loja[loja.nome] = {
                'loja': loja,
                'total_vendas': total_vendas_loja,
                'total_parcelas': total_de_parcelas_vencidas + total_de_parcelas_pagas + total_de_parcelas_a_vencer,
                'parcelas_pagas': total_de_parcelas_pagas,
                'parcelas_vencidas': total_de_parcelas_vencidas,
                'parcelas_a_vencer': total_de_parcelas_a_vencer,
                'total_pagas': total_pagas,
                'total_vencidas': total_vencidas,
                'total_a_vencer': total_a_vencer,
                'total_desativados_vencidas': total_desativados_vencidas,
                'total_desativados_a_vencer': total_desativados_a_vencer,
                'qtd_desativados_vencidas': qtd_desativados_vencidas,
                'qtd_desativados_a_vencer': qtd_desativados_a_vencer,
                'total_repasses': total_repasses,
                'valor_total_parcelas': valor_total_parcelas,
            }

        return {
            'dados_por_loja': dados_por_loja,
            'data_geracao': timezone.now(),
            'usuario': self.request.user,
        }
