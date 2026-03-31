from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.views import View
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Q
from vendas.models import Loja
from vendas.views import BaseView
from .models import Parcelamento, Produto

class ProdutoListView(PermissionRequiredMixin, ListView):
    model = Produto
    template_name = 'produtos/produto_list.html'
    paginate_by = 10
    context_object_name = 'items'
    permission_required = 'produtos.view_produto'

    def get_queryset(self):
        # Se o usuário tem permissão view_all_produtos, mostra todos (ativos e desativados)
        # Caso contrário, filtra pelos produtos permitidos da loja atual
        if self.request.user.has_perm('produtos.view_all_produtos'):
            queryset = Produto.objects.all()
        else:
            loja_id = self.request.session.get('loja_id')
            loja = Loja.objects.filter(id=loja_id).first() if loja_id else None
            if loja:
                queryset = loja.produtos_permitidos_qs()
            else:
                queryset = Produto.objects.filter(ativo=True)

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(nome__icontains=search)

        return queryset.order_by('nome')


class ProdutoDeleteView(PermissionRequiredMixin, View):
    permission_required = 'produtos.delete_produto'
    
    def post(self, request, pk):
        produto = get_object_or_404(Produto, pk=pk)
        produto.ativo = False
        produto.save()
        messages.success(request, f'Produto "{produto.nome}" foi desativado com sucesso.')
        return redirect('produtos:produtos')


class ProdutoActivateView(PermissionRequiredMixin, View):
    permission_required = 'produtos.delete_produto'
    
    def post(self, request, pk):
        produto = get_object_or_404(Produto, pk=pk)
        produto.ativo = True
        produto.save()
        messages.success(request, f'Produto "{produto.nome}" foi ativado com sucesso.')
        return redirect('produtos:produtos')

class MarcaDeactivateView(PermissionRequiredMixin, View):
    permission_required = 'produtos.change_marca'
    
    def post(self, request, pk):
        from .models import Marca
        marca = get_object_or_404(Marca, pk=pk)
        marca.ativo = False
        marca.save()
        messages.success(request, f'Marca "{marca.nome}" foi desativada com sucesso.')
        return redirect('produtos:marcas')

class MarcaActivateView(PermissionRequiredMixin, View):
    permission_required = 'produtos.change_marca'
    
    def post(self, request, pk):
        from .models import Marca
        marca = get_object_or_404(Marca, pk=pk)
        marca.ativo = True
        marca.save()
        messages.success(request, f'Marca "{marca.nome}" foi ativada com sucesso.')
        return redirect('produtos:marcas')


class ProdutoPDFView(PermissionRequiredMixin, View):
    permission_required = 'produtos.view_produto'

    def get(self, request):
        from weasyprint import HTML

        if request.user.has_perm('produtos.view_all_produtos'):
            queryset = Produto.objects.all()
        else:
            loja_id = request.session.get('loja_id')
            loja = Loja.objects.filter(id=loja_id).first() if loja_id else None
            if loja:
                queryset = loja.produtos_permitidos_qs()
            else:
                queryset = Produto.objects.filter(ativo=True)

        search = request.GET.get('search')
        if search:
            queryset = queryset.filter(nome__icontains=search)

        produtos = queryset.order_by('nome')

        html_str = render_to_string('produtos/produto_pdf.html', {
            'produtos': produtos,
            'search': search,
            'gerado_em': timezone.localtime(timezone.now()),
        })

        pdf_file = HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="produtos.pdf"'
        return response


class ParcelamentoDeleteView(PermissionRequiredMixin, View):
    permission_required = 'produtos.delete_parcelamento'

    def post(self, request, pk):
        parcelamento = get_object_or_404(Parcelamento, pk=pk)
        parcelamento.delete()
        messages.success(request, f'Parcelamento {parcelamento.qtd_vezes}x removido com sucesso.')
        return redirect('produtos:parcelamentos')


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
            qs = modelo.objects.all()

            # Filtra por lojas_permitidas se o modelo suportar e o usuário não tiver permissão global
            if (
                loja_id
                and hasattr(modelo, 'lojas_permitidas')
                and not self.request.user.has_perm(f'{modelo._meta.app_label}.view_all_{modelo._meta.model_name}')
            ):
                qs = qs.filter(
                    Q(lojas_permitidas__isnull=True) |
                    Q(lojas_permitidas__id=loja_id)
                ).distinct()

            # Filtro por ativo (somente se o modelo tiver o campo)
            if hasattr(modelo, 'ativo'):
                ativo = self.request.GET.get('ativo', 'true')
                if ativo == 'false':
                    qs = qs.filter(ativo=False)
                elif ativo == 'all':
                    pass
                else:
                    qs = qs.filter(ativo=True)

            search = self.request.GET.get('search')
            if search:
                qs = qs.filter(nome__icontains=search)
            return qs

    class GeneratedCreateView(PermissionRequiredMixin, CreateView):
        model = modelo
        form_class = form
        template_name = f'{template_dir}/{modelo._meta.model_name}_create.html'
        success_url = f'/{modelo._meta.model_name}'
        permission_required = f'{modelo._meta.app_label}.add_{modelo._meta.model_name}'
        
        def form_valid(self, form):
            form.instance.loja = Loja.objects.get(pk=self.request.session.get('loja_id'))
            return super().form_valid(form)

        def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs['user'] = self.request.user
            return kwargs

    class GeneratedDetailView(PermissionRequiredMixin, DetailView):
        model = modelo
        template_name = f'{template_dir}/{modelo._meta.model_name}_detail.html'
        context_object_name = modelo._meta.model_name
        permission_required = f'{modelo._meta.app_label}.view_{modelo._meta.model_name}'

        def get_context_data(self, **kwargs):
            context = super().get_context_data(**kwargs)
            context['form'] = form(instance=self.object, disabled=True) if form else None
            return context

    class GeneratedUpdateView(PermissionRequiredMixin ,UpdateView):
        model = modelo
        form_class = form
        template_name = f'{template_dir}/{modelo._meta.model_name}_edit.html'
        success_url = f'/{modelo._meta.model_name}'
        permission_required = f'{modelo._meta.app_label}.change_{modelo._meta.model_name}'

        def get_form_kwargs(self):
            kwargs = super().get_form_kwargs()
            kwargs['user'] = self.request.user
            return kwargs

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
