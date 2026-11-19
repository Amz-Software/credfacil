"""Relatórios de vendas e de solicitações (formulário e folha de impressão)."""
from collections import defaultdict
from datetime import datetime, timedelta
import logging

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Count, Exists, F, OuterRef, Q
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import FormView, TemplateView

from vendas.forms import RelatorioSolicitacoesForm, RelatorioVendasForm
from vendas.models import Cliente, Loja, Pagamento, PreAnaliseRapida, Venda


logger = logging.getLogger(__name__)


def _clientes_quitados_por_loja(pagamento_ids):
    """Retorna IDs de clientes com pagamento IPX integralmente quitado por loja.

    `pagamento_ids` deve conter somente pagamentos que possuem ao menos uma
    parcela dentro do período selecionado. A quitação é avaliada sobre todas
    as parcelas do pagamento, e não apenas sobre as parcelas do período.
    """
    pagamento_ids = set(pagamento_ids)
    clientes_por_loja = defaultdict(set)
    if not pagamento_ids:
        return clientes_por_loja

    pagamentos_quitados = (
        Pagamento.objects.filter(
            id__in=pagamento_ids,
            tipo_pagamento__nome='IPX',
            venda__cliente_id__isnull=False,
        )
        .annotate(
            total_parcelas=Count('parcelas_pagamento', distinct=True),
            parcelas_pagas=Count(
                'parcelas_pagamento',
                filter=Q(parcelas_pagamento__pago=True),
                distinct=True,
            ),
        )
        .filter(total_parcelas__gt=0, total_parcelas=F('parcelas_pagas'))
        .values_list('venda__loja_id', 'venda__cliente_id')
        .distinct()
    )

    for loja_id, cliente_id in pagamentos_quitados:
        clientes_por_loja[loja_id].add(cliente_id)
    return clientes_por_loja


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
            
        analise_online_normalizada = (analise_online or '').strip().lower()
        if analise_online_normalizada in ('true', 'false', '1', '0'):
            filtros['analise_credito__analise_online'] = analise_online_normalizada in ('true', '1')

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
        
        analise_online_normalizada = (analise_online or '').strip().lower()
        if analise_online_normalizada in ('true', 'false', '1', '0'):
            filtros['analises_credito_venda__analise_online'] = analise_online_normalizada in ('true', '1')

        # faz a query
        segunda_compra_do_cliente = PreAnaliseRapida.objects.filter(
            cliente_gerado_id=OuterRef('cliente_id'), segunda_compra=True,
        )
        self.vendas = Venda.objects.filter(is_deleted=False, **filtros).annotate(
            is_segunda_compra=Exists(segunda_compra_do_cliente),
        ).distinct()

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
