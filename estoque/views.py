"""Endpoints de consulta de estoque/IMEI usados pelas telas de venda.

As telas de gestão de estoque (entradas, inventário, fornecedores) foram
removidas; os modelos continuam em estoque/models.py.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from estoque.models import EstoqueImei
from produtos.models import Produto
from vendas.models import Loja, Venda


@login_required
def check_produtos(request, produto_id):
    produto = get_object_or_404(Produto, pk=produto_id)
    if produto.tipo.numero_serial:
        return JsonResponse({'serializado': True})
    else:
        return JsonResponse({'serializado': False})
    
    
class EstoqueImeiSearchView(View):
    def get(self, request, *args, **kwargs):
        term = request.GET.get('term', '')
        user = request.user
        produto_id = request.GET.get('produto_id', None)
        loja_id = self.request.session.get('loja_id')
        loja = get_object_or_404(Loja, pk=loja_id)
        queryset = EstoqueImei.objects.filter(vendido=False, produto_entrada__entrada__venda_liberada=True, cancelado=False).filter(
            Q(imei__icontains=term) | Q(produto__nome__icontains=term) | Q(loja__nome__icontains=term)
        )
        
        if not user.has_perm('estoque.can_view_all_imei'):
            queryset = queryset.filter(loja=loja)
        
        if produto_id:
            queryset = queryset.filter(produto_id=produto_id)
        
        results = []
        for imei in queryset:
            if not user.has_perm('estoque.can_view_all_imei'):
                text = f'{imei.imei} - {imei.produto.nome}'
            else:
                text = f'{imei.imei} - {imei.produto.nome} | {imei.produto.loja.nome}'
            results.append({
                'id': imei.id,
                'text': text
            })
        return JsonResponse({'results': results})
    
class EstoqueImeiSearchEditView(View):
    def get(self, request, *args, **kwargs):
        term = request.GET.get('term', '')
        produto_id = request.GET.get('produto_id', None)
        loja_id = self.request.session.get('loja_id')
        venda_id = self.request.session.get('venda_id')
        loja = get_object_or_404(Loja, pk=loja_id)
        queryset = EstoqueImei.objects.filter(
            Q(imei__icontains=term) | Q(produto__nome__icontains=term)
        ).filter(loja=loja).filter(vendido=False, cancelado=False)
        if produto_id:
            queryset = queryset.filter(produto_id=produto_id)
        results = []
        for imei in queryset:
            results.append({
                'id': imei.imei,
                'text': f'{imei.imei} - {imei.produto.nome}'
            })

        if venda_id:
            venda = get_object_or_404(Venda, pk=venda_id)
            for item in venda.itens_venda.all():
                if item.imei:
                    results.append({
                        'id': item.imei,
                        'text': f'{item.imei} - {item.produto.nome}'
                    })
        return JsonResponse({'results': results})
    



    
def buscar_imei_por_produto(request):
    if request.method == 'GET':
        produto_id = request.GET.get('produto_id')
        imei_antigo = request.GET.get('imei')

        if produto_id:
            imeis = EstoqueImei.objects.filter(produto_id=produto_id, vendido=False, cancelado=False).exclude(imei=imei_antigo) if imei_antigo else EstoqueImei.objects.filter(produto_id=produto_id, vendido=False)
            imeis_list = [{'id': imei.id, 'imei': f'{imei.imei} - {imei.produto.nome}'} for imei in imeis]
            return JsonResponse({'imeis': imeis_list})
        
    return JsonResponse({'error': 'Produto não encontrado'}, status=404)
