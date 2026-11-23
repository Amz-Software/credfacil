"""Solicitações de crédito: listagem, exportação, cadastro e edição do cliente."""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from produtos.models import Marca, Parcelamento, Produto
from vendas.exports import gerar_planilha_clientes
from vendas.filtros import filtrar_clientes_solicitacao, lojas_selecionadas
from vendas.forms import (
    AnaliseCreditoClienteForm,
    AnaliseCreditoClienteImeiForm,
    ClienteForm,
    ClienteTelefoneForm,
    ComprovantesClienteEditForm,
    ComprovantesClienteForm,
    ContatoAdicionalEditForm,
    ContatoAdicionalForm,
    erro_pelo_menos_um_contato,
    InformacaoPessoalEditForm,
    InformacaoPessoalForm,
    user_is_analista_or_admin,
)
from vendas.models import AnaliseCreditoCliente, Cliente, Loja
from vendas.services import analise as servico_analise
from vendas.services.kpis import analises_visiveis, contar_por_status

from .analise import _pode_observar_solicitacao
from .base import BaseView


logger = logging.getLogger(__name__)


def _avisar_solicitacoes_existentes(
    request, *, cpf=None, rg=None, nome=None, telefone=None,
    telefone_secundario=None, exclude_cliente_id=None
):
    filtros = Q()
    if cpf:
        filtros |= Q(cpf=cpf)
    if rg:
        filtros |= Q(rg=rg)
    if nome:
        filtros |= Q(nome__iexact=nome)
    telefones = [numero for numero in [telefone, telefone_secundario] if numero]
    if telefones:
        filtros |= Q(telefone__in=telefones) | Q(telefone_secundario__in=telefones)

    if not filtros:
        return

    qs = Cliente.objects.filter(filtros).select_related('analise_credito')
    if exclude_cliente_id:
        qs = qs.exclude(pk=exclude_cliente_id)

    if not qs.exists():
        return

    detalhes = []
    for cliente in qs[:5]:
        analise = getattr(cliente, 'analise_credito', None)
        if analise:
            detalhes.append(
                f"Solicitação #{analise.id} (Cliente {cliente.nome}, status {analise.get_status_display()})"
            )
        else:
            detalhes.append(f"Cliente #{cliente.id} ({cliente.nome})")

    total = qs.count()
    sufixo = f" +{total - len(detalhes)}" if total > len(detalhes) else ""
    mensagem = "⚠️ Existem solicitações de crédito com dados já cadastrados (CPF, RG, Nome ou Telefones). "
    mensagem += "Encontradas: " + "; ".join(detalhes) + sufixo
    messages.warning(request, mensagem)


class ClienteListView(BaseView, PermissionRequiredMixin, ListView):
    model = Cliente
    template_name = 'cliente/cliente_list.html'
    context_object_name = 'items'
    paginate_by = 10
    permission_required = 'vendas.view_cliente'
    

    def get_queryset(self):
        return filtrar_clientes_solicitacao(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        loja_id = self.request.session.get('loja_id')
        
        context['loja'] = Loja.objects.get(id=loja_id)
        context['lojas'] = Loja.objects.all()
        context['loja_credfacil'] = Loja.objects.filter(credfacil=True).first()

        context['kpis'] = contar_por_status(analises_visiveis(self.request.user, loja_id))
        context['status_choices'] = AnaliseCreditoCliente.STATUS_CHOICES
        context['current_status'] = self.request.GET.get('status', '')
        context['status_app_choices'] = AnaliseCreditoCliente.STATUS_APP_CHOICES
        context['current_status_app'] = self.request.GET.get('status_app', '')
        context['lojas_selecionadas'] = lojas_selecionadas(self.request)
        return context


class ClienteExportExcelView(PermissionRequiredMixin, View):
    """Exporta em .xlsx os clientes da listagem de solicitações.

    Usa exatamente os mesmos filtros da tela, então o arquivo reflete o que
    o usuário está vendo — sem o recorte de paginação.
    """

    permission_required = 'vendas.view_cliente'

    def get(self, request, *args, **kwargs):
        clientes = filtrar_clientes_solicitacao(request).only(
            'nome', 'cpf', 'telefone', 'cidade'
        )
        return gerar_planilha_clientes(clientes.iterator())


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
    

def _produtos_json_list(somente_ativos: bool = True) -> list[dict]:
    """Produtos no formato consumido pelo JS dos formulários de solicitação."""
    qs = Produto.objects.filter(ativo=True) if somente_ativos else Produto.objects.all()
    return [
        {
            'id': p['id'],
            'nome': p['nome'],
            'is_iphone': p['is_iphone'],
            'valor': float(p['valor'] or 0),
            'entrada': float(p['entrada_cliente'] or 0),
            'marca_id': p['marca_id'],
        }
        for p in qs.values('id', 'nome', 'is_iphone', 'valor', 'entrada_cliente', 'marca_id')
    ]


def _parcelamentos_json_list() -> list[dict]:
    """Parcelamentos por marca — fonte única dos juros em todas as telas."""
    return [
        {
            'id': p['id'],
            'marca_id': p['marca_id'],
            'qtd_vezes': p['qtd_vezes'],
            'porcentagem_juros': float(p['porcentagem_juros']),
        }
        for p in Parcelamento.objects.values('id', 'marca_id', 'qtd_vezes', 'porcentagem_juros')
    ]


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
        
        context['produtos_json'] = json.dumps(_produtos_json_list())
        context['parcelamentos_json'] = json.dumps(_parcelamentos_json_list())

        loja_id_ctx = self.request.session.get('loja_id')
        marcas_qs = Marca.objects.filter(ativo=True)
        if loja_id_ctx:
            marcas_qs = marcas_qs.filter(
                Q(lojas_permitidas__isnull=True) |
                Q(lojas_permitidas__id=loja_id_ctx)
            ).distinct()
        marcas = marcas_qs.values('id', 'nome', 'cor', 'icone')
        marcas_list = [
            {
                'id': m['id'],
                'nome': m['nome'],
                'cor': m['cor'] or '#007bff',
                'icone': m['icone'] or 'bx bx-mobile'
            }
            for m in marcas
        ]
        context['marcas_json'] = json.dumps(marcas_list)
        context['tem_marcas'] = len(marcas_list) > 0

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
            
            _avisar_solicitacoes_existentes(
                request,
                cpf=form_cliente.cleaned_data.get('cpf'),
                rg=form_cliente.cleaned_data.get('rg'),
                nome=form_cliente.cleaned_data.get('nome'),
                telefone=form_cliente.cleaned_data.get('telefone'),
                telefone_secundario=form_cliente.cleaned_data.get('telefone_secundario'),
            )
            
            contato_adicional_val = form_adicional.cleaned_data.get('contato')
            contato_pessoal_val = form_informacao.cleaned_data.get('contato_pessoal')
            endereco_adicional_val = (form_adicional.cleaned_data.get('endereco_adicional') or '').strip().lower()
            endereco_pessoal_val = (form_informacao.cleaned_data.get('endereco_pessoal') or '').strip().lower()
            nome_adicional_val = (form_adicional.cleaned_data.get('nome_adicional') or '').strip().lower()
            nome_pessoal_val = (form_informacao.cleaned_data.get('nome_pessoal') or '').strip().lower()

            conflito = False
            if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
                conflito = True
                form_adicional.add_error('contato', 'Contato Adicional não pode ser igual ao Contato de Informações Pessoais.')
                form_informacao.add_error('contato_pessoal', 'Contato de Informações Pessoais não pode ser igual ao Contato Adicional.')
            if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
                conflito = True
                form_adicional.add_error('endereco_adicional', 'Endereço Adicional não pode ser igual ao Endereço de Informações Pessoais.')
                form_informacao.add_error('endereco_pessoal', 'Endereço de Informações Pessoais não pode ser igual ao Endereço Adicional.')
            if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
                conflito = True
                form_adicional.add_error('nome_adicional', 'Nome Adicional não pode ser igual ao Nome de Informações Pessoais.')
                form_informacao.add_error('nome_pessoal', 'Nome de Informações Pessoais não pode ser igual ao Nome Adicional.')

            if conflito:
                messages.error(request, "❌ Informações Pessoais e Contato Adicional não podem ser iguais.")
                return self.form_invalid(form_cliente)

            # Pelo menos um dos dois contatos deve estar completo.
            erro_contato = erro_pelo_menos_um_contato(form_adicional, form_informacao)
            if erro_contato:
                form_adicional.add_error('contato', erro_contato)
                form_informacao.add_error('contato_pessoal', erro_contato)
                messages.error(request, f"❌ {erro_contato}")
                context = self.get_context_data(
                    form_cliente=form_cliente,
                    form_adicional=form_adicional,
                    form_informacao=form_informacao,
                    form_comprovantes=form_comprovantes,
                    form_analise_credito=form_analise_credito,
                )
                return self.render_to_response(context)

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
                logger.warning("Loja %s não encontrada ao salvar a solicitação", loja_id)
                return self.form_invalid(form_cliente)

            analise = form_analise_credito.save(commit=False)
            analise.cliente = cliente
            analise.loja = loja
            analise.criado_por = request.user
            analise.modificado_por = request.user
            analise.save(user=request.user)

            messages.success(request, "✅ Soliticitação cadastrado com sucesso")
            return redirect(self.success_url)

        else:
            
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


def _aprovar_apos_salvar(request, analise_credito) -> None:
    """Botão "Aprovar" da tela de edição: salva o formulário e aprova no mesmo POST.

    Antes o servidor redirecionava (GET) para a URL vinda do campo oculto, o que
    exigia aprovar por GET e permitia redirecionar para qualquer endereço.
    """
    if not request.POST.get('aprovar_apos_salvar'):
        return
    if not request.user.has_perm('vendas.change_status_analise'):
        messages.error(request, 'Você não tem permissão para aprovar análises de crédito.')
        return
    servico_analise.aprovar_analise(analise_credito, request.user)
    messages.success(request, '✅ Análise de crédito aprovada com sucesso')


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

        context['observacoes_solicitacao'] = (
            analise.observacoes
            .select_related('autor')
            .order_by('-criado_em')
        )
        context['pode_adicionar_observacao'] = _pode_observar_solicitacao(self.request.user)

        context['status_app_choices'] = AnaliseCreditoCliente.STATUS_APP_CHOICES

        context['produtos_json'] = json.dumps(_produtos_json_list(somente_ativos=False))
        context['parcelamentos_json'] = json.dumps(_parcelamentos_json_list())

        loja_id_ctx = self.request.session.get('loja_id')
        marcas_qs = Marca.objects.filter(ativo=True)
        if loja_id_ctx:
            marcas_qs = marcas_qs.filter(
                Q(lojas_permitidas__isnull=True) |
                Q(lojas_permitidas__id=loja_id_ctx)
            ).distinct()
        marcas = marcas_qs.values('id', 'nome', 'cor', 'icone')
        marcas_list = [
            {
                'id': m['id'],
                'nome': m['nome'],
                'cor': m['cor'] or '#007bff',
                'icone': m['icone'] or 'bx bx-mobile'
            }
            for m in marcas
        ]
        context['marcas_json'] = json.dumps(marcas_list)
        context['tem_marcas'] = len(marcas_list) > 0

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        # Verifica se a venda já foi gerada
        venda_gerada = self.object.analise_credito.venda is not None

        # ANALISTA/ADMIN (ou permissão de editar venda finalizada) podem editar
        # mesmo depois da venda gerada. VENDEDOR/GERENTE só podem editar antes.
        pode_editar_pos_venda = user_is_analista_or_admin(user) or user.has_perm('vendas.can_edit_finished_sale')
        if venda_gerada and not pode_editar_pos_venda:
            messages.warning(request, "❌ Somente ANALISTA/ADMIN podem editar a solicitação após a venda ser gerada.")
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
            
            _avisar_solicitacoes_existentes(
                request,
                cpf=form_cliente.cleaned_data.get('cpf'),
                rg=form_cliente.cleaned_data.get('rg'),
                nome=form_cliente.cleaned_data.get('nome'),
                telefone=form_cliente.cleaned_data.get('telefone'),
                telefone_secundario=form_cliente.cleaned_data.get('telefone_secundario'),
                exclude_cliente_id=self.object.pk,
            )
            
            contato_adicional_val = form_adicional.cleaned_data.get('contato')
            contato_pessoal_val = form_informacao.cleaned_data.get('contato_pessoal')
            endereco_adicional_val = (form_adicional.cleaned_data.get('endereco_adicional') or '').strip().lower()
            endereco_pessoal_val = (form_informacao.cleaned_data.get('endereco_pessoal') or '').strip().lower()
            nome_adicional_val = (form_adicional.cleaned_data.get('nome_adicional') or '').strip().lower()
            nome_pessoal_val = (form_informacao.cleaned_data.get('nome_pessoal') or '').strip().lower()

            conflito = False
            if contato_adicional_val and contato_pessoal_val and contato_adicional_val == contato_pessoal_val:
                conflito = True
                form_adicional.add_error('contato', 'Contato Adicional não pode ser igual ao Contato de Informações Pessoais.')
                form_informacao.add_error('contato_pessoal', 'Contato de Informações Pessoais não pode ser igual ao Contato Adicional.')
            if endereco_adicional_val and endereco_pessoal_val and endereco_adicional_val == endereco_pessoal_val:
                conflito = True
                form_adicional.add_error('endereco_adicional', 'Endereço Adicional não pode ser igual ao Endereço de Informações Pessoais.')
                form_informacao.add_error('endereco_pessoal', 'Endereço de Informações Pessoais não pode ser igual ao Endereço Adicional.')
            if nome_adicional_val and nome_pessoal_val and nome_adicional_val == nome_pessoal_val:
                conflito = True
                form_adicional.add_error('nome_adicional', 'Nome Adicional não pode ser igual ao Nome de Informações Pessoais.')
                form_informacao.add_error('nome_pessoal', 'Nome de Informações Pessoais não pode ser igual ao Nome Adicional.')

            if conflito:
                messages.error(request, "❌ Informações Pessoais e Contato Adicional não podem ser iguais.")
                return self.form_invalid(form_cliente)

            # Pelo menos um dos dois contatos deve estar completo.
            erro_contato = erro_pelo_menos_um_contato(form_adicional, form_informacao)
            if erro_contato:
                form_adicional.add_error('contato', erro_contato)
                form_informacao.add_error('contato_pessoal', erro_contato)
                messages.error(request, f"❌ {erro_contato}")
                context = self.get_context_data(
                    form_cliente=form_cliente,
                    form_adicional=form_adicional,
                    form_informacao=form_informacao,
                    form_comprovantes=form_comprovantes,
                    form_analise_credito=form_analise_credito,
                )
                return self.render_to_response(context)

            contato_adicional = form_adicional.save()
            informacao = form_informacao.save()
            comprovantes = form_comprovantes.save()
            analise_credito = form_analise_credito.save()

            cliente = form_cliente.save(commit=False)
            cliente.contato_adicional = contato_adicional
            cliente.informacao_pessoal = informacao
            cliente.comprovantes = comprovantes
            cliente.save(user=user)
            messages.success(request, "✅ Soliticitação atualizada com sucesso")
            
            _aprovar_apos_salvar(request, analise_credito)
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
            form_informacao=form_informacao,
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

        # O template consome produtos_json/parcelamentos_json para montar os cards
        # de valor. Sem eles o JSON.parse do template estourava e derrubava todo o
        # bloco de script — inclusive o handler do botão Aprovar.
        context['produtos_json'] = json.dumps(_produtos_json_list(somente_ativos=False))
        context['parcelamentos_json'] = json.dumps(_parcelamentos_json_list())

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        user = request.user

        form_cliente = ClienteTelefoneForm(request.POST, instance=self.object, user=user)
        form_analise_credito = AnaliseCreditoClienteImeiForm(request.POST, instance=self.object.analise_credito, user=request.user)

        if form_cliente.is_valid() and form_analise_credito.is_valid():
            analise_credito = form_analise_credito.save()
            cliente = form_cliente.save(commit=False)
            cliente.save(user=user)
            messages.success(request, "✅ Soliticitação atualizada com sucesso")
            _aprovar_apos_salvar(request, analise_credito)
            return redirect(self.success_url)
        else:
            messages.error(request, "❌ Erro ao atualizar Soliticitação. Verifique os dados e tente novamente.")

        context = self.get_context_data(
            form_cliente=form_cliente,
            form_analise_credito=form_analise_credito,
        )
        return self.render_to_response(context)


@permission_required('vendas.change_cliente', raise_exception=True)
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
