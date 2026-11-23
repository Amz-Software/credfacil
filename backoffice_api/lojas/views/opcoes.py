"""Opções do formulário de loja (usuários, gerentes e modelos bloqueáveis)."""
from django.contrib.auth import get_user_model
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.response import Response

from produtos.models import Produto

from ...nucleo.permissoes import QualquerPermissao
from ..base import TAGS, LojasBaseView
from ..serializers import ProdutoResumoSerializer, UsuarioResumoSerializer, pode_editar_campos_restritos


@extend_schema(tags=TAGS)
class OpcoesFormularioView(LojasBaseView):
    """Mesmas listas do `LojaForm` da tela Django: usuários ativos e produtos ativos."""

    permissoes = {'GET': [QualquerPermissao('vendas.add_loja', 'vendas.change_loja')]}

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        usuarios = get_user_model().objects.filter(is_active=True).order_by('first_name', 'last_name', 'username')
        produtos = Produto.objects.filter(ativo=True).order_by('nome', 'id')
        return Response({
            'usuarios': UsuarioResumoSerializer(usuarios, many=True).data,
            'produtos': ProdutoResumoSerializer(produtos, many=True).data,
            'pode_editar_campos_restritos': pode_editar_campos_restritos(request.user),
        })
