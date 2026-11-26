"""Etapas da análise de crédito: status, app, iCloud, IMEI, geração da venda e observações."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import View

from vendas.models import AnaliseCreditoCliente, Cliente, Loja, ObservacaoSolicitacao
from vendas.services import analise as servico_analise, ErroDeNegocio
from vendas.services.venda import gerar_venda_da_analise


logger = logging.getLogger(__name__)


def _redirecionar_com_erro(request, erro: ErroDeNegocio, cliente_pk):
    """Mostra o erro de negócio e leva à edição da solicitação quando o dado é corrigível lá."""
    messages.error(request, f'❌ {erro.mensagem}')
    if erro.corrigir_na_edicao and cliente_pk:
        return redirect('vendas:cliente_update', pk=cliente_pk)
    return redirect('vendas:cliente_list')


class ClienteInstallAppView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        if cliente.loja_id != request.session.get('loja_id'):
            messages.error(request, "Ação não autorizada para esta loja.")
            return redirect('vendas:cliente_list')

        servico_analise.marcar_instalacao_pendente(cliente.analise_credito)
        messages.success(request, "Status alterado para Confirmação Pendente.")
        return redirect('vendas:cliente_list')


class ClienteConfirmInstalledView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        try:
            servico_analise.confirmar_instalacao_vendedor(cliente.analise_credito, request.user)
        except ErroDeNegocio as erro:
            messages.error(request, erro.mensagem)
            return redirect('vendas:cliente_list')
        messages.success(request, "✅ Instalação confirmada! Aguardando analista informar IMEI.")
        return redirect('vendas:cliente_list')


class ClienteStatusAppUpdateView(PermissionRequiredMixin, View):
    permission_required = 'vendas.change_cliente'

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        try:
            analise = servico_analise.atualizar_status_aplicativo(
                cliente.analise_credito, request.POST.get('status_app'),
            )
        except ErroDeNegocio as erro:
            messages.error(request, erro.mensagem)
        else:
            messages.success(
                request,
                f"Status do aplicativo atualizado para {analise.get_status_aplicativo_display()}.",
            )
        return redirect('vendas:cliente_update', pk=pk)


@permission_required('vendas.add_venda', raise_exception=True)
def gerar_venda(request, cliente_id):
    if request.method != 'POST':
        return redirect('vendas:cliente_list')
    cliente = get_object_or_404(Cliente, id=cliente_id)
    get_object_or_404(Loja, id=request.session.get('loja_id'))
    if not Loja.objects.filter(credfacil=True).exists():
        raise Http404("Loja CredFacil não encontrada.")

    try:
        gerar_venda_da_analise(cliente, request.user, bloquear_imei_de_venda_cancelada=True)
    except ErroDeNegocio as erro:
        return _redirecionar_com_erro(request, erro, cliente.pk)

    messages.success(request, f"✅ Venda criada para o cliente {cliente.nome}!")
    return redirect('vendas:cliente_list')


def _mudar_status_analise(request, id, transicao, mensagem_sucesso):
    analise = AnaliseCreditoCliente.objects.filter(id=id).first()
    if analise is None:
        messages.error(request, 'Análise de crédito não encontrada')
    else:
        transicao(analise, request.user)
        messages.success(request, mensagem_sucesso)
    return redirect('vendas:cliente_list')


@require_POST
@permission_required('vendas.change_status_analise', raise_exception=True)
def aprovar_analise_credito(request, id):
    return _mudar_status_analise(
        request, id, servico_analise.aprovar_analise, '✅ Análise de crédito aprovada com sucesso',
    )


@require_POST
@permission_required('vendas.change_analisecreditocliente', raise_exception=True)
def cancelar_analise_credito(request, id):
    if not request.user.has_perm('vendas.change_status_analise'):
        messages.error(request, 'Você não tem permissão para cancelar análises de crédito')
        return redirect('vendas:cliente_list')
    return _mudar_status_analise(
        request, id, servico_analise.cancelar_analise, 'Análise de crédito cancelada com sucesso',
    )


@require_POST
@permission_required('vendas.change_status_analise', raise_exception=True)
def reprovar_analise_credito(request, id):
    return _mudar_status_analise(
        request, id, servico_analise.reprovar_analise, 'Análise de crédito reprovada com sucesso',
    )


@permission_required('vendas.change_analisecreditocliente', raise_exception=True)
def informar_imei_analise(request, pk):
    """Analista informa o IMEI da análise (GET mostra o formulário)."""
    analise = get_object_or_404(AnaliseCreditoCliente, pk=pk)
    try:
        servico_analise.exigir_analista(request.user, 'Apenas analistas podem informar o IMEI.')
        servico_analise.validar_pode_informar_imei(analise)
        if request.method != 'POST':
            return render(request, 'vendas/informar_imei_analise.html', {
                'analise': analise, 'cliente': analise.cliente,
            })
        loja = get_object_or_404(Loja, id=request.session.get('loja_id'))
        imei = (request.POST.get('imei_informado') or '').strip()
        _, criado = servico_analise.informar_imei(analise, request.user, imei, loja)
    except ErroDeNegocio as erro:
        return _redirecionar_com_erro(request, erro, analise.cliente_id)

    acao = 'criado e associado' if criado else 'associado'
    messages.success(request, f'IMEI {imei} {acao} com sucesso à análise.')
    messages.success(request, 'IMEI informado com sucesso! Venda liberada para geração pelo vendedor.')
    return redirect('vendas:cliente_list')


class _AcaoNaAnaliseView(PermissionRequiredMixin, View):
    """POST que aplica uma transição do serviço à análise do cliente e volta para a lista."""

    def executar(self, request, analise):
        raise NotImplementedError

    def post(self, request, pk):
        cliente = get_object_or_404(Cliente, pk=pk)
        try:
            mensagem = self.executar(request, cliente.analise_credito)
        except ErroDeNegocio as erro:
            messages.error(request, f'❌ {erro.mensagem}')
        else:
            messages.success(request, mensagem)
        return redirect('vendas:cliente_list')


class AnalistaConfirmInstalledView(_AcaoNaAnaliseView):
    permission_required = 'vendas.change_status_analise'

    def executar(self, request, analise):
        servico_analise.confirmar_instalacao_analista(analise, request.user)
        return "✅ Instalação confirmada pelo analista! Venda liberada para geração."


class ClienteConfigurarIcloudView(_AcaoNaAnaliseView):
    """Vendedor confirma a configuração inicial do iPhone e informa os 4 últimos dígitos do IMEI"""
    permission_required = 'vendas.change_cliente'

    def executar(self, request, analise):
        servico_analise.configurar_icloud(analise, request.user, request.POST.get('imei_ultimos_digitos'))
        return f'✅ Configuração iCloud confirmada para {analise.cliente.nome}'


class AnalistaConfirmIcloudView(_AcaoNaAnaliseView):
    """Analista confirma que o iCloud foi configurado corretamente"""
    permission_required = 'vendas.change_status_analise'

    def executar(self, request, analise):
        servico_analise.confirmar_icloud_analista(analise, request.user)
        return f'✅ Configuração iCloud confirmada pelo analista para {analise.cliente.nome}'


GRUPOS_OBSERVACAO_SOLICITACAO = ['ANALISTA', 'ADMINISTRADOR', 'SUPERADMIN']


def _pode_observar_solicitacao(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=GRUPOS_OBSERVACAO_SOLICITACAO).exists()


@login_required
def adicionar_observacao_solicitacao(request, pk):
    analise = get_object_or_404(AnaliseCreditoCliente, pk=pk)

    if not _pode_observar_solicitacao(request.user):
        messages.error(request, '❌ Você não tem permissão para adicionar observações nesta solicitação.')
        return redirect('vendas:cliente_update', pk=analise.cliente_id)

    if request.method != 'POST':
        return redirect('vendas:cliente_update', pk=analise.cliente_id)

    texto = (request.POST.get('texto') or '').strip()
    if not texto:
        messages.warning(request, '⚠️ A observação não pode estar vazia.')
        return redirect(f"{reverse('vendas:cliente_update', kwargs={'pk': analise.cliente_id})}#tab-historico")

    ObservacaoSolicitacao.objects.create(
        analise_credito=analise,
        autor=request.user,
        texto=texto,
    )
    messages.success(request, '✅ Observação adicionada ao histórico.')
    return redirect(f"{reverse('vendas:cliente_update', kwargs={'pk': analise.cliente_id})}#tab-historico")
