"""Vendas: listagem, edição, documentos, troca de produto, cancelamento, carnê e contrato."""
import base64
from io import BytesIO
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.timezone import localtime, now
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView, View
from django_select2.views import AutoResponseView
from pypix import Pix
import qrcode

from estoque.models import Estoque, EstoqueImei
from produtos.models import Parcelamento, Produto
from vendas.forms import (
    FormaPagamentoEdicaoEspecialFormSet,
    FormaPagamentoEditFormSet,
    ProdutoVendaEdicaoEspecialFormSet,
    ProdutoVendaEditFormSet,
    VendaDocumentosForm,
    VendaEdicaoEspecialForm,
    VendaForm,
)
from vendas.models import Loja, Pagamento, ProdutoVenda, TipoPagamento, Venda

from .base import BaseView


logger = logging.getLogger(__name__)


class VendaListView(BaseView, PermissionRequiredMixin, ListView):
    model = Venda
    template_name = 'venda/venda_list.html'
    context_object_name = 'vendas'
    paginate_by = 10
    permission_required = 'vendas.view_venda'
    
    def get_queryset(self):
        query = Venda.objects.all()
        data_filter = self.request.GET.get('search')
        venda_id = self.request.GET.get('venda_id', '').strip()
        loja = self.request.GET.get('loja_id')
        cliente_nome = self.request.GET.get('cliente_nome')
        vendas_canceladas = self.request.GET.get('vendas_canceladas')
        vendas_trocadas = self.request.GET.get('vendas_trocadas')
        
        if loja:
            query = query.filter(loja__id=loja)
        if data_filter:
            query = query.filter(data_venda=data_filter)
        if venda_id:
            query = query.filter(pk=venda_id) if venda_id.isdigit() else query.none()
        if cliente_nome:
            query = query.filter(cliente__nome__icontains=cliente_nome)
        if vendas_canceladas:
            query = query.filter(is_deleted=True)
        else:
            query = query.filter(is_deleted=False)
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
        except Exception:
            logger.exception("Erro ao processar a venda %s", self.object.pk)
            messages.error(self.request, "❌ Não foi possível salvar a venda. Tente novamente ou fale com o suporte.")
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

        if not (form.is_valid() and produto_venda_formset.is_valid() and pagamento_formset.is_valid()):
            return self.form_invalid(form)

        alterou_somente_imei = self._alterou_somente_imei(
            produto_venda_formset,
            pagamento_formset,
        )

        try:
            with transaction.atomic():
                self._atualizar_venda(form, loja)
                self._processar_produtos(produto_venda_formset, loja)
                if not alterou_somente_imei:
                    self._processar_pagamentos(pagamento_formset, loja)
                messages.success(self.request, 'Venda atualizada com sucesso')
            return super().form_valid(form)
        except Exception:
            logger.exception("Erro ao processar a venda %s", self.object.pk)
            messages.error(self.request, "❌ Não foi possível salvar a venda. Tente novamente ou fale com o suporte.")
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

    @staticmethod
    def _alterou_somente_imei(produto_formset, pagamento_formset):
        campos_produto_alterados = {
            campo
            for produto_form in produto_formset.forms
            for campo in produto_form.changed_data
        }
        if campos_produto_alterados != {'imei'}:
            return False

        for pagamento_form in pagamento_formset.forms:
            nome_campo = pagamento_form.add_prefix('parcelas')
            if nome_campo not in pagamento_form.data:
                continue

            parcelas_anteriores = pagamento_form.initial.get('parcelas')
            parcelas_informadas = pagamento_form.cleaned_data.get('parcelas')
            if parcelas_informadas != parcelas_anteriores:
                return False

        return True

    def _processar_pagamentos(self, formset, loja):
        pagamentos_modificados = formset.save(commit=False)

        produto_venda = self.object.itens_venda.first()
        produto_base = produto_venda.produto if produto_venda else None
        quantidade_base = produto_venda.quantidade if produto_venda else 0

        entrada_base = None
        totais_parcelamento = {}
        if produto_base and produto_base.valor:
            entrada_base = produto_base.entrada_cliente * quantidade_base
            marca = produto_base.marca
            parcelamentos_marca = {
                p.qtd_vezes: p.porcentagem_juros
                for p in Parcelamento.objects.filter(marca=marca)
            }
            valor_financiado_base = (produto_base.valor - produto_base.entrada_cliente) * quantidade_base
            for qtd, juros in parcelamentos_marca.items():
                totais_parcelamento[qtd] = valor_financiado_base + (valor_financiado_base * juros / 100)

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
            return redirect('vendas:venda_trocar', pk=pk)

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
        except Exception:
            logger.exception("Erro ao trocar produto da venda %s", pk)
            messages.error(request, "❌ Não foi possível trocar o produto. Tente novamente ou fale com o suporte.")

        return redirect('vendas:venda_detail', pk=pk)


    # Métodos de validação e restauração de estoque e IMEI removidos - não são mais necessários

@require_POST
@permission_required('vendas.delete_venda', raise_exception=True)
def cancelar_venda(request, id):
    venda = get_object_or_404(Venda, id=id)
    data_atual = localtime(now()).date()

    if venda.is_deleted:
        messages.warning(request, 'Venda já cancelada')
        return redirect('vendas:venda_list')
    
    venda.is_deleted = True
    venda.save(user=request.user)
    messages.success(request, 'Venda cancelada com sucesso')
    return redirect('vendas:venda_list')


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

    produtos = loja.produtos_permitidos_qs(require_stock=True)
    if term:
        produtos = produtos.filter(nome__icontains=term)

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


@permission_required('vendas.view_venda', raise_exception=True)
def folha_carne_view(request, pk, tipo):
    venda = get_object_or_404(Venda, pk=pk)
    pagamento_carne = Pagamento.objects.filter(
        venda=venda,
        tipo_pagamento__carne=True
    ).first()

    if not pagamento_carne:
        messages.error(request, 'Venda não possui pagamento em carnê ou promissória')
        return redirect('vendas:venda_list')

    parcelas = pagamento_carne.parcelas_pagamento.order_by('numero_parcela')
    cliente = venda.cliente
    loja = get_object_or_404(Loja, credfacil=True)

    # O carnê SEMPRE reflete o pagamento IPX: valor da parcela = pagamento.valor / parcelas
    # e a quantidade vem do próprio pagamento. Nunca usa o valor do produto.
    quantidade_parcelas = pagamento_carne.parcelas or parcelas.count()
    valor_parcela_pagamento = (
        pagamento_carne.valor / pagamento_carne.parcelas
        if pagamento_carne.parcelas else pagamento_carne.valor
    )

    parcelas_info = []
    for i, parcela in enumerate(parcelas):
        valor = f"{valor_parcela_pagamento:.2f}"
        txid = f"{pagamento_carne.pk:04d}{i+1:02d}"
        descricao = f"{cliente.nome} - Parcela {i+1} de {quantidade_parcelas}"
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
        'quantidade_parcelas': quantidade_parcelas,
        'nome_cliente': cliente.nome.title(),
        'endereco_cliente': cliente.endereco,
        'cpf': cliente.cpf,
        'data_atual': localtime(now()).date(),
        'parcelas_info': parcelas_info,
        'loja': loja,
        'numero_loja': loja.telefone,
    }

    return render(request, "venda/folha_carne.html", context)


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


@permission_required('vendas.view_venda', raise_exception=True)
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
