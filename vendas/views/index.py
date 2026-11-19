"""Página inicial, guia, KPIs de status, gráfico de vendas e relatório PDF do dashboard."""
from collections import defaultdict
from io import BytesIO
import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import get_template
from django.utils import timezone
from django.views.generic import TemplateView, View
import weasyprint

from vendas.models import Cliente, Loja, Pagamento, Parcela, Venda
from vendas.services.kpis import analises_visiveis, contar_por_status, resumo_carteira_loja

from .relatorios import _clientes_quitados_por_loja


logger = logging.getLogger(__name__)


class IndexView(LoginRequiredMixin, TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja = self._get_active_loja()
        if self.request.user.has_perm('vendas.can_view_your_dashboard'):
            context.update(resumo_carteira_loja(loja))
        context['loja'] = loja
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


class CaixaKpiCountsView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        analises = analises_visiveis(request.user, request.session.get('loja_id'))
        return JsonResponse(contar_por_status(analises))


class GuiaView(LoginRequiredMixin, TemplateView):
    template_name = 'guia.html'


class GraficoTemplateView(PermissionRequiredMixin, TemplateView):
    template_name = 'dash/index.html'
    permission_required = 'vendas.can_view_all_dashboard'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_get = self.request.GET.get('loja')
        loja = Loja.objects.filter(id=loja_get) if loja_get else Loja.objects.all()

        vendas = Venda.objects.filter(is_deleted=False, loja__in=loja)
        
        data_inicio = self.request.GET.get('data_inicio')
        data_fim = self.request.GET.get('data_fim')
        
        # Filtro de Total de Vendas separadamente (Baseado na Data da Venda)
        vendas_periodo = vendas
        if data_inicio:
            vendas_periodo = vendas_periodo.filter(data_venda__gte=data_inicio)
        if data_fim:
            vendas_periodo = vendas_periodo.filter(data_venda__lte=data_fim + ' 23:59:59')
        total_vendas = vendas_periodo.count()
        
        # Parse dates
        from datetime import datetime
        dt_inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date() if data_inicio else None
        dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date() if data_fim else None
        parcelas_qs = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX'
        ).select_related('pagamento', 'pagamento__venda')

        parcelas_por_venda = defaultdict(list)

        vendas_ids_validas = set()
        for parcela in parcelas_qs:
            dt_base = parcela.data_pagamento if (parcela.pago and parcela.data_pagamento) else parcela.data_vencimento
            if dt_base:
                if dt_inicio and dt_base < dt_inicio: continue
                if dt_fim and dt_base > dt_fim: continue
            
            parcelas_por_venda[parcela.pagamento.venda_id].append(parcela)
            vendas_ids_validas.add(parcela.pagamento.venda_id)

        pagamentos_no_periodo_ids = {
            parcela.pagamento_id
            for parcelas in parcelas_por_venda.values()
            for parcela in parcelas
        }
        clientes_quitados_por_loja = _clientes_quitados_por_loja(pagamentos_no_periodo_ids)
        clientes_quitados_ids = set().union(*clientes_quitados_por_loja.values()) if clientes_quitados_por_loja else set()
            
        # Otimizar laço de Vendas para iterar apenas as que tem parcelas no período
        vendas = vendas.filter(id__in=vendas_ids_validas)


        total_de_parcelas_vencidas = total_de_parcelas_pagas = total_de_parcelas_a_vencer = 0
        total_pagas = total_vencidas = total_a_vencer = total_geral_parcelas = 0
        clientes_vencidos_ids = set()

        valores_por_loja = defaultdict(lambda: {
            'total_pagas': 0, 'total_vencidas': 0, 'total_a_vencer': 0,
            'total_desativados_vencidas': 0, 'total_desativados_a_vencer': 0,
            'total_cobranca_vencidas': 0, 'total_cobranca_a_vencer': 0,
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

            if qtd_vencidas > 0 and venda.cliente_id:
                clientes_vencidos_ids.add(venda.cliente_id)

            valor_vencidas = sum(p.valor for p in parcelas_vencidas)
            valor_pagas = sum(p.valor_pago_efetivo for p in parcelas_pagas)
            valor_a_vencer = sum(p.valor for p in parcelas_a_vencer)

            total_vencidas += valor_vencidas
            total_pagas += valor_pagas
            total_a_vencer += valor_a_vencer

            valores_por_loja[loja_nome]['total_a_vencer'] += valor_a_vencer
            valores_por_loja[loja_nome]['total_vencidas'] += valor_vencidas
            valores_por_loja[loja_nome]['total_pagas'] += valor_pagas

            # Calcular desativados por loja Filtrado
            parcelas_desativadas_loja = Parcela.objects.filter(
                pagamento__venda=venda,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__desativado=True,
                pago=False
            )
            if dt_inicio:
                parcelas_desativadas_loja = parcelas_desativadas_loja.filter(data_vencimento__gte=dt_inicio)
            if dt_fim:
                parcelas_desativadas_loja = parcelas_desativadas_loja.filter(data_vencimento__lte=dt_fim)

            for parcela_desativada in parcelas_desativadas_loja:
                if parcela_desativada.data_vencimento < timezone.now().date():
                    valores_por_loja[loja_nome]['total_desativados_vencidas'] += parcela_desativada.valor
                else:
                    valores_por_loja[loja_nome]['total_desativados_a_vencer'] += parcela_desativada.valor

            # Calcular cobrança por loja Filtrado
            parcelas_cobranca_loja = Parcela.objects.filter(
                pagamento__venda=venda,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__flag_atrasado=True,
                pago=False
            )
            if dt_inicio:
                parcelas_cobranca_loja = parcelas_cobranca_loja.filter(data_vencimento__gte=dt_inicio)
            if dt_fim:
                parcelas_cobranca_loja = parcelas_cobranca_loja.filter(data_vencimento__lte=dt_fim)

            for parcela_cobranca in parcelas_cobranca_loja:
                if parcela_cobranca.data_vencimento < timezone.now().date():
                    valores_por_loja[loja_nome]['total_cobranca_vencidas'] += parcela_cobranca.valor
                else:
                    valores_por_loja[loja_nome]['total_cobranca_a_vencer'] += parcela_cobranca.valor

            # DASH MENSAL: soma por mês/ano
            for p in parcelas:
                mes_ano = p.data_vencimento.strftime('%Y-%m')
                if p.pago and not p.pagamento_efetuado:
                    dash_mensal_lojas[loja_nome][mes_ano]['pago'] += float(p.valor_pago_efetivo)
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
            total_geral = valores['total_pagas'] + valores['total_vencidas'] + valores['total_a_vencer'] + valores['total_desativados_vencidas'] + valores['total_desativados_a_vencer'] + valores.get('total_cobranca_vencidas', 0) + valores.get('total_cobranca_a_vencer', 0)
            valores['pct_pagas'] = round((valores['total_pagas'] / total_geral) * 100, 2) if total_geral else 0
            valores['pct_vencidas'] = round((valores['total_vencidas'] / total_geral) * 100, 2) if total_geral else 0
            valores['pct_desativados'] = round(((valores['total_desativados_vencidas'] + valores['total_desativados_a_vencer']) / total_geral) * 100, 2) if total_geral else 0
            valores['pct_cobrancas'] = round(((valores.get('total_cobranca_vencidas', 0) + valores.get('total_cobranca_a_vencer', 0)) / total_geral) * 100, 2) if total_geral else 0

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
        if dt_inicio:
            parcelas_desativadas = parcelas_desativadas.filter(data_vencimento__gte=dt_inicio)
        if dt_fim:
            parcelas_desativadas = parcelas_desativadas.filter(data_vencimento__lte=dt_fim)

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

        # --- CÁLCULO DOS CLIENTES EM COBRANÇA ---
        total_cobranca_vencidas = 0
        total_cobranca_a_vencer = 0
        qtd_cobranca_vencidas = 0
        qtd_cobranca_a_vencer = 0

        # Busca parcelas de clientes em cobrança (apenas não pagas)
        parcelas_cobranca = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX',
            pagamento__flag_atrasado=True,
            pago=False
        )

        for parcela in parcelas_cobranca:
            if parcela.data_vencimento < timezone.now().date():
                total_cobranca_vencidas += parcela.valor
                qtd_cobranca_vencidas += 1
            else:
                total_cobranca_a_vencer += parcela.valor
                qtd_cobranca_a_vencer += 1

        # Total de pagamentos em cobrança
        total_pagamentos_cobranca = Pagamento.objects.filter(
            venda__in=vendas,
            tipo_pagamento__nome='IPX',
            flag_atrasado=True
        ).count()

        # --- CÁLCULO DO VALOR TOTAL DE REPASSES ---
        # Repasse segue a mesma regra do relatório de vendas: uma soma por venda
        # filtrada pela data da venda, sem multiplicar pela quantidade de itens.
        total_repasses = 0
        repasses_por_loja = defaultdict(lambda: 0)

        for venda in vendas_periodo.select_related('loja'):
            valor_repasse = venda.repasse_logista or 0
            total_repasses += valor_repasse
            loja_nome = venda.loja.nome if venda.loja else 'Desconhecida'
            repasses_por_loja[loja_nome] += valor_repasse

        context.update({
            'data_inicio_get': data_inicio,
            'data_fim_get': data_fim,
            'loja_get': int(loja_get) if loja_get else None,
            'lojas': Loja.objects.all(),
            'total_vendas_loja': total_vendas,
            'total_de_parcelas_geral': total_geral_parcelas,
            'parcelas_vencidas': total_de_parcelas_vencidas,
            'clientes_vencidos': len(clientes_vencidos_ids),
            'clientes_quitados': len(clientes_quitados_ids),
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
            'total_cobranca_vencidas': total_cobranca_vencidas,
            'total_cobranca_a_vencer': total_cobranca_a_vencer,
            'qtd_cobranca_vencidas': qtd_cobranca_vencidas,
            'qtd_cobranca_a_vencer': qtd_cobranca_a_vencer,
            'total_pagamentos_cobranca': total_pagamentos_cobranca,
            'total_repasses': total_repasses,
            'repasses_por_loja': {
                nome: repasses_por_loja[nome]
                for nome in sorted(repasses_por_loja, key=str.lower)
            },
            'dados_lojas': json.dumps(
                {nome: valores_por_loja[nome] for nome in sorted(valores_por_loja, key=str.lower)},
                default=str,
            ),
            'dash_mensal_lojas': json.dumps(dash_mensal_json, default=str) if loja_get else None,
        })

        return context


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
        loja_get = self.request.GET.get('loja')
        data_inicio = self.request.GET.get('data_inicio')
        data_fim = self.request.GET.get('data_fim')

        if loja_get:
            lojas = Loja.objects.filter(id=loja_get)
        else:
            lojas = Loja.objects.all()

        vendas = Venda.objects.filter(is_deleted=False, loja__in=lojas)
        
        vendas_periodo = vendas
        if data_inicio:
            vendas_periodo = vendas_periodo.filter(data_venda__gte=data_inicio)
        if data_fim:
            vendas_periodo = vendas_periodo.filter(data_venda__lte=data_fim + ' 23:59:59')
            
        from datetime import datetime
        dt_inicio = datetime.strptime(data_inicio, "%Y-%m-%d").date() if data_inicio else None
        dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date() if data_fim else None

        parcelas_qs = Parcela.objects.filter(
            pagamento__venda__in=vendas,
            pagamento__tipo_pagamento__nome='IPX'
        ).select_related('pagamento', 'pagamento__venda')

        parcelas_por_venda = defaultdict(list)
        for parcela in parcelas_qs:
            dt_base = parcela.data_pagamento if (parcela.pago and parcela.data_pagamento) else parcela.data_vencimento
            if dt_base:
                if dt_inicio and dt_base < dt_inicio: continue
                if dt_fim and dt_base > dt_fim: continue
            parcelas_por_venda[parcela.pagamento.venda_id].append(parcela)

        pagamentos_no_periodo_ids = {
            parcela.pagamento_id
            for parcelas in parcelas_por_venda.values()
            for parcela in parcelas
        }
        clientes_quitados_por_loja = _clientes_quitados_por_loja(pagamentos_no_periodo_ids)
        total_clientes_quitados_ids = set().union(*clientes_quitados_por_loja.values()) if clientes_quitados_por_loja else set()
        lojas_por_id = dict(lojas.values_list('id', 'nome'))
        lojas_quitadas_por_cliente = defaultdict(set)
        for loja_id, cliente_ids in clientes_quitados_por_loja.items():
            for cliente_id in cliente_ids:
                lojas_quitadas_por_cliente[cliente_id].add(lojas_por_id.get(loja_id, 'Desconhecida'))
        nomes_clientes_quitados = dict(
            Cliente.objects.filter(id__in=total_clientes_quitados_ids)
            .values_list('id', 'nome')
        )
        clientes_quitados_lista = [
            {
                'nome': nomes_clientes_quitados[cliente_id],
                'lojas': ', '.join(sorted(lojas_cliente, key=str.casefold)),
            }
            for cliente_id, lojas_cliente in lojas_quitadas_por_cliente.items()
            if cliente_id in nomes_clientes_quitados
        ]
        clientes_quitados_lista.sort(key=lambda cliente: cliente['nome'].casefold())

        # Dados por loja
        dados_por_loja = {}
        total_clientes_vencidos_ids = set()
        
        for loja in lojas:
            # Repasses and vendas counts rely on the period's sales (not installments)
            vendas_loja_periodo = vendas_periodo.filter(loja=loja)
            total_vendas_loja = vendas_loja_periodo.count()
            
            # Pegar vendas que tem parcelas no periodo
            vendas_ativas_IDs = [vid for vid, parcs in parcelas_por_venda.items() if parcs and parcs[0].pagamento.venda.loja_id == loja.id]
            vendas_loja_ativos = Venda.objects.filter(id__in=vendas_ativas_IDs)

            # Calcular KPIs para esta loja
            total_de_parcelas_vencidas = total_de_parcelas_pagas = total_de_parcelas_a_vencer = 0
            total_pagas = total_vencidas = total_a_vencer = 0
            clientes_vencidos_ids = set()

            for venda_id in vendas_ativas_IDs:
                parcelas = parcelas_por_venda.get(venda_id, [])
                venda = parcelas[0].pagamento.venda if parcelas else None
                
                parcelas_vencidas = [p for p in parcelas if p.data_vencimento < timezone.now().date() and not p.pago and not p.pagamento_efetuado]
                parcelas_pagas = [p for p in parcelas if p.pago and not p.pagamento_efetuado]
                parcelas_a_vencer = [p for p in parcelas if p.data_vencimento >= timezone.now().date() and not p.pago and not p.pagamento_efetuado]

                total_de_parcelas_vencidas += len(parcelas_vencidas)
                total_de_parcelas_pagas += len(parcelas_pagas)
                total_de_parcelas_a_vencer += len(parcelas_a_vencer)

                total_vencidas += sum(p.valor for p in parcelas_vencidas)
                total_pagas += sum(p.valor_pago_efetivo for p in parcelas_pagas)
                total_a_vencer += sum(p.valor for p in parcelas_a_vencer)

                if parcelas_vencidas and venda and venda.cliente_id:
                    clientes_vencidos_ids.add(venda.cliente_id)
                    total_clientes_vencidos_ids.add(venda.cliente_id)

            # Calcular desativados para esta loja
            parcelas_desativadas = Parcela.objects.filter(
                pagamento__venda__loja=loja,
                pagamento__venda__is_deleted=False,
                pagamento__tipo_pagamento__nome='IPX',
                pagamento__desativado=True,
                pago=False
            )
            if dt_inicio:
                parcelas_desativadas = parcelas_desativadas.filter(data_vencimento__gte=dt_inicio)
            if dt_fim:
                parcelas_desativadas = parcelas_desativadas.filter(data_vencimento__lte=dt_fim)
            
            total_desativados_vencidas = sum(p.valor for p in parcelas_desativadas if p.data_vencimento < timezone.now().date())
            total_desativados_a_vencer = sum(p.valor for p in parcelas_desativadas if p.data_vencimento >= timezone.now().date())
            qtd_desativados_vencidas = sum(1 for p in parcelas_desativadas if p.data_vencimento < timezone.now().date())
            qtd_desativados_a_vencer = sum(1 for p in parcelas_desativadas if p.data_vencimento >= timezone.now().date())

            # Calcular repasses para esta loja (por periodo da venda)
            # Mantém paridade com o relatório de vendas: uma soma por venda.
            total_repasses = sum(venda.repasse_logista or 0 for venda in vendas_loja_periodo)

            # Valor total das parcelas
            valor_total_parcelas = total_pagas + total_vencidas + total_a_vencer + total_desativados_vencidas + total_desativados_a_vencer

            dados_por_loja[loja.nome] = {
                'loja': loja,
                'total_vendas': total_vendas_loja,
                'total_parcelas': total_de_parcelas_vencidas + total_de_parcelas_pagas + total_de_parcelas_a_vencer,
                'parcelas_pagas': total_de_parcelas_pagas,
                'parcelas_vencidas': total_de_parcelas_vencidas,
                'clientes_vencidos': len(clientes_vencidos_ids),
                'clientes_quitados': len(clientes_quitados_por_loja.get(loja.id, set())),
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

        # Ordena as lojas em ordem alfabética (case-insensitive) para o relatório
        dados_por_loja = {
            nome: dados_por_loja[nome]
            for nome in sorted(dados_por_loja, key=str.lower)
        }

        return {
            'dados_por_loja': dados_por_loja,
            'clientes_vencidos': len(total_clientes_vencidos_ids),
            'clientes_quitados': len(total_clientes_quitados_ids),
            'clientes_quitados_lista': clientes_quitados_lista,
            'data_geracao': timezone.now(),
            'usuario': self.request.user,
        }
