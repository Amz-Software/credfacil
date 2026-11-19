"""Pré-análise rápida (backoffice do analista)."""
from datetime import datetime, timedelta
from io import BytesIO
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import get_template
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, ListView, View
import weasyprint

from vendas.forms import PreAnaliseRapidaConsultaSerasaForm
from vendas.models import Loja, PreAnaliseRapida


logger = logging.getLogger(__name__)


# ─── Pré-análise rápida (backoffice do analista) ────────────────────────────

PERMISSAO_VER_TODAS_PRE_ANALISES = 'vendas.view_all_analise_credito'


def _pode_ver_todas_pre_analises(user):
    return bool(user.is_superuser or user.has_perm(PERMISSAO_VER_TODAS_PRE_ANALISES))


def _lojas_visiveis_pre_analise(user):
    """Lojas que o usuário pode enxergar na listagem de análises rápidas."""
    if _pode_ver_todas_pre_analises(user):
        return Loja.objects.all().order_by('nome')

    lojas_ids = set(user.lojas.values_list('id', flat=True))
    if getattr(user, 'loja_id', None):
        lojas_ids.add(user.loja_id)
    return Loja.objects.filter(id__in=lojas_ids).order_by('nome')


def _inicio_do_dia(data):
    """Primeiro instante do dia no fuso do projeto (USE_TZ=True).

    Filtrar por intervalo de datetime evita o lookup `__date`, que no MySQL
    depende das tabelas de fuso horário carregadas no banco.
    """
    return timezone.make_aware(datetime.combine(data, datetime.min.time()))


def _pode_gerar_relatorio_pre_analise(user):
    """Apenas analista ou administrador podem gerar o relatório em PDF."""
    return bool(
        user.is_superuser
        or user.groups.filter(name__in=['ANALISTA', 'ADMINISTRADOR']).exists()
    )


def _filtrar_pre_analises(request):
    """Aplica ao queryset os mesmos filtros usados na listagem e no PDF."""
    qs = PreAnaliseRapida.objects.select_related(
        'loja', 'criado_por', 'analisado_por', 'cliente_gerado'
    ).order_by('-criado_em')

    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)

    search = request.GET.get('q')
    if search:
        qs = qs.filter(Q(nome_completo__icontains=search) | Q(cpf__icontains=search))

    user = request.user
    if not _pode_ver_todas_pre_analises(user):
        qs = qs.filter(loja_id__in=_lojas_visiveis_pre_analise(user).values('id'))

    loja_id = request.GET.get('loja', '')
    if loja_id.isdigit():
        qs = qs.filter(loja_id=int(loja_id))

    data_inicio = parse_date(request.GET.get('data_inicio', ''))
    if data_inicio:
        qs = qs.filter(criado_em__gte=_inicio_do_dia(data_inicio))

    data_fim = parse_date(request.GET.get('data_fim', ''))
    if data_fim:
        qs = qs.filter(criado_em__lt=_inicio_do_dia(data_fim + timedelta(days=1)))

    return qs


class PreAnaliseRapidaListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = PreAnaliseRapida
    template_name = 'pre_analise_rapida/list.html'
    context_object_name = 'pre_analises'
    permission_required = 'vendas.view_cliente'
    paginate_by = 25

    def get_queryset(self):
        return _filtrar_pre_analises(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['status_atual'] = self.request.GET.get('status', '')
        ctx['q'] = self.request.GET.get('q', '')
        ctx['lojas'] = _lojas_visiveis_pre_analise(self.request.user)
        ctx['loja_atual'] = self.request.GET.get('loja', '')
        ctx['data_inicio'] = self.request.GET.get('data_inicio', '')
        ctx['data_fim'] = self.request.GET.get('data_fim', '')
        ctx['pode_decidir'] = self.request.user.has_perm('vendas.change_status_analise')
        ctx['pode_gerar_pdf'] = _pode_gerar_relatorio_pre_analise(self.request.user)
        return ctx


class PreAnaliseRapidaPDFView(LoginRequiredMixin, View):
    """Relatório em PDF das pré-análises rápidas, com os mesmos filtros da
    listagem. Restrito a analista/administrador."""

    def get(self, request, *args, **kwargs):
        if not _pode_gerar_relatorio_pre_analise(request.user):
            raise PermissionDenied

        qs = _filtrar_pre_analises(request)

        status_map = dict(PreAnaliseRapida.STATUS_CHOICES)
        linhas = []
        for pre in qs:
            status_label = status_map.get(pre.status, pre.status)
            if pre.status == 'A' and pre.finalizada:
                status_label = f'{status_label} (Finalizada)'
            linhas.append({
                'cliente': pre.nome_completo,
                'cpf': pre.cpf,
                'loja': pre.loja.nome if pre.loja else '—',
                'status': status_label,
                'enviado_em': timezone.localtime(pre.criado_em).strftime('%d/%m/%Y %H:%M'),
            })

        loja_id = request.GET.get('loja', '')
        loja_filtro = Loja.objects.filter(pk=loja_id).first() if loja_id.isdigit() else None
        status_filtro = status_map.get(request.GET.get('status', ''), 'Todos')

        html = get_template('pre_analise_rapida/pre_analise_rapida_pdf.html').render({
            'linhas': linhas,
            'total': len(linhas),
            'loja_filtro': loja_filtro.nome if loja_filtro else 'Todas',
            'status_filtro': status_filtro,
            'data_inicio': request.GET.get('data_inicio', '') or '—',
            'data_fim': request.GET.get('data_fim', '') or '—',
            'gerado_em': timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M'),
        })
        pdf_buffer = BytesIO()
        weasyprint.HTML(string=html).write_pdf(pdf_buffer)
        pdf_buffer.seek(0)
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        filename = f'pre_analises_rapidas_{timezone.now():%Y%m%d_%H%M%S}.pdf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


def _pode_gerenciar_consulta_serasa(user):
    """Mesma regra usada no cadastro do cliente: analista/quem pode decidir
    análise ou quem tem permissão explícita de consulta Serasa."""
    return bool(
        user.is_superuser
        or user.has_perm('vendas.change_status_analise')
        or user.has_perm('vendas.view_consulta_serasa')
        or user.groups.filter(name='ANALISTA').exists()
    )


class PreAnaliseRapidaDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = PreAnaliseRapida
    template_name = 'pre_analise_rapida/detail.html'
    context_object_name = 'pre_analise'
    permission_required = 'vendas.view_cliente'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['pode_decidir'] = self.request.user.has_perm('vendas.change_status_analise')
        ctx['pode_gerenciar_serasa'] = _pode_gerenciar_consulta_serasa(self.request.user)
        ctx['form_consulta_serasa'] = PreAnaliseRapidaConsultaSerasaForm(instance=self.object)
        return ctx


@login_required
def anexar_consulta_serasa_pre_analise(request, pk):
    """Analista anexa (ou substitui) a consulta Serasa direto na análise rápida.
    O arquivo é copiado para os comprovantes do cliente quando a proposta é gerada."""
    pre = get_object_or_404(PreAnaliseRapida, pk=pk)

    if not _pode_gerenciar_consulta_serasa(request.user):
        raise PermissionDenied('Você não tem permissão para anexar a consulta Serasa.')

    if request.method != 'POST':
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)

    if pre.finalizada:
        messages.warning(
            request,
            'Esta análise já virou proposta. Anexe a consulta Serasa direto no cadastro do cliente.',
        )
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)

    form = PreAnaliseRapidaConsultaSerasaForm(request.POST, request.FILES, instance=pre)
    if not form.is_valid():
        for erro in form.errors.get('consulta_serasa', ['Arquivo inválido.']):
            messages.error(request, erro)
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)

    pre.anexar_consulta_serasa(form.cleaned_data['consulta_serasa'], user=request.user)
    messages.success(
        request,
        '✅ Consulta Serasa anexada. Ela já virá preenchida quando a proposta for gerada.',
    )
    return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)


@login_required
def remover_consulta_serasa_pre_analise(request, pk):
    pre = get_object_or_404(PreAnaliseRapida, pk=pk)

    if not _pode_gerenciar_consulta_serasa(request.user):
        raise PermissionDenied('Você não tem permissão para remover a consulta Serasa.')

    if request.method != 'POST':
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)

    if pre.finalizada:
        messages.warning(request, 'Esta análise já virou proposta e não pode mais ser alterada.')
    elif pre.remover_consulta_serasa(user=request.user):
        messages.success(request, 'Consulta Serasa removida da análise rápida.')
    else:
        messages.info(request, 'Nenhuma consulta Serasa anexada nesta análise.')
    return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)


@permission_required('vendas.change_status_analise', raise_exception=True)
def aprovar_pre_analise_rapida(request, pk):
    pre = get_object_or_404(PreAnaliseRapida, pk=pk)
    if pre.status != 'P':
        messages.warning(request, 'Esta pré-análise já foi decidida.')
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)
    pre.aprovar(user=request.user)
    messages.success(request, '✅ Pré-análise pré-aprovada com sucesso.')
    return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)


@permission_required('vendas.change_status_analise', raise_exception=True)
def reprovar_pre_analise_rapida(request, pk):
    pre = get_object_or_404(PreAnaliseRapida, pk=pk)
    if pre.status != 'P':
        messages.warning(request, 'Esta pré-análise já foi decidida.')
        return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)
    motivo = request.POST.get('motivo') if request.method == 'POST' else None
    pre.reprovar(user=request.user, motivo=motivo)
    messages.success(request, 'Pré-análise reprovada.')
    return redirect('vendas:pre_analise_rapida_detalhe', pk=pk)
