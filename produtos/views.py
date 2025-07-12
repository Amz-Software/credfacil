from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from produtos.forms import OpcaoProdutoFormSet
from vendas.models import Loja
from vendas.views import BaseView
from .models import Produto
from django.contrib import messages

class ProdutoListView(PermissionRequiredMixin, ListView):
    model = Produto
    template_name = 'produtos/produto_list.html'
    paginate_by = 10
    context_object_name = 'items'
    permission_required = 'produtos.view_produto'

    def get_queryset(self):
        queryset = Produto.objects.all()
        search = self.request.GET.get('search')
        if search:
            return queryset.filter(nome__icontains=search)
        return queryset.order_by('nome')

def generate_views(modelo, form=None, paginacao=10, template_dir=''):
    """
    Gera as views baseadas no modelo e nos parâmetros fornecidos.
    
    :param modelo: Modelo do Django.
    :param form: Classe de formulário associada.
    :param paginacao: Número de itens por página na ListView.
    :param template_dir: Diretório onde os templates estão armazenados.
    :return: Dicionário contendo as views geradas.
    """

    class GeneratedListView(PermissionRequiredMixin, ListView):
        model = modelo
        template_name = f'{template_dir}/{modelo._meta.model_name}_list.html'
        paginate_by = paginacao
        context_object_name = 'items'
        permission_required = f'{modelo._meta.app_label}.view_{modelo._meta.model_name}'

        def get_queryset(self):
            loja_id = self.request.session.get('loja_id')
            search = self.request.GET.get('search')
            if search:
                return modelo.objects.filter(nome__icontains=search)
            return modelo.objects.all()

    class GeneratedCreateView(PermissionRequiredMixin, CreateView):
        model = modelo
        form_class = form
        template_name = f'{template_dir}/{modelo._meta.model_name}_create.html'
        success_url = f'/{modelo._meta.model_name}'
        permission_required = f'{modelo._meta.app_label}.add_{modelo._meta.model_name}'
        
        def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs['user'] = self.request.user
            return kwargs

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            if modelo is Produto:
                ctx['opcoes_formset'] = OpcaoProdutoFormSet(self.request.POST or None)
            return ctx

        def form_valid(self, form):
            form.instance.loja = Loja.objects.get(pk=self.request.session.get('loja_id'))
            self.object = form.save()
            if modelo is Produto:
                fs = OpcaoProdutoFormSet(self.request.POST, instance=self.object)
                if fs.is_valid():
                    fs.save()
                else:
                    return self.form_invalid(form)
            return super().form_valid(form)

    class GeneratedDetailView(PermissionRequiredMixin, DetailView):
        model = modelo
        template_name = f'{template_dir}/{modelo._meta.model_name}_detail.html'
        context_object_name = modelo._meta.model_name
        permission_required = f'{modelo._meta.app_label}.view_{modelo._meta.model_name}'

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context['form'] = form(instance=self.object, disabled=True) if form else None
            return context

    class GeneratedUpdateView(PermissionRequiredMixin, UpdateView):
        model = modelo
        form_class = form
        template_name = f'{template_dir}/{modelo._meta.model_name}_edit.html'
        success_url = f'/{modelo._meta.model_name}'
        permission_required = f'{modelo._meta.app_label}.change_{modelo._meta.model_name}'

        def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs['user'] = self.request.user
            return kwargs

        def get_context_data(self, **kwargs):
            ctx = super().get_context_data(**kwargs)
            if modelo is Produto:
                ctx['opcoes_formset'] = OpcaoProdutoFormSet(self.request.POST or None, instance=self.object)
            return ctx

        def form_valid(self, form):
            self.object = form.save()
            if modelo is Produto:
                fs = OpcaoProdutoFormSet(self.request.POST, instance=self.object)
            if fs.is_valid():
                fs.save()
            else:
                error_messages = fs.errors
                messages.error(self.request, f'Erro ao salvar Opções do Produto: {error_messages}')
                return self.form_invalid(form)
            return super().form_valid(form)

    class GeneratedDeleteView(PermissionRequiredMixin, DeleteView):
        model = modelo
        success_url = reverse_lazy(f'{modelo._meta.model_name}s:{modelo._meta.model_name}s')
        permission_required = f'{modelo._meta.app_label}.delete_{modelo._meta.model_name}'

    return {
        'list_view': GeneratedListView,
        'create_view': GeneratedCreateView,
        'detail_view': GeneratedDetailView,
        'update_view': GeneratedUpdateView,
        'delete_view': GeneratedDeleteView
    }
