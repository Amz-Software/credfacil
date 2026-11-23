from django.contrib.auth.models import Permission
from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission


class LojaPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve"):
            return user.has_perm("vendas.view_loja")
        if action == "create":
            return user.has_perm("vendas.add_loja")
        if action in ("update", "partial_update", "replicar_qrcode"):
            return user.has_perm("vendas.change_loja")
        if action == "repasses":
            return user.has_perm("financeiro.view_repasse") or user.has_perm("financeiro.add_repasse")
        if action == "destroy":
            return user.has_perm("vendas.delete_loja")

        return False


class SolicitacaoCreditoPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve", "kpis", "log_consulta_serasa"):
            return user.has_perm("vendas.view_cliente")
        if action == "create":
            return user.has_perm("vendas.add_cliente")
        if action in ("update", "partial_update", "imei_telefone", "configurar_icloud"):
            return user.has_perm("vendas.change_cliente")
        # Decisões da análise são só do analista: `change_cliente` (vendedor) não basta.
        if action in ("aprovar", "reprovar", "status_app"):
            return user.has_perm("vendas.change_status_analise")
        if action in (
            "cancelar",
            "confirmar_app",
            "confirmar_leitura_qrcode",
            "gerar_qrcode_instalacao_endpoint",
            "instalar_app",
            "analista_confirm_icloud",
            "analista_confirm_installed",
            "informar_imei_analise",
        ):
            return user.has_perm("vendas.change_status_analise") or user.has_perm("vendas.change_cliente")
        if action == "gerar_venda":
            return user.has_perm("vendas.add_venda")
        if action == "destroy":
            return user.has_perm("vendas.delete_cliente")

        return False


class PreAnaliseRapidaPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve"):
            return user.has_perm("vendas.view_cliente")
        if action == "create":
            return user.has_perm("vendas.add_cliente")
        if action in ("aprovar", "reprovar"):
            return user.has_perm("vendas.change_status_analise")
        if action == "marcar_finalizada":
            return user.has_perm("vendas.add_venda") or user.has_perm("vendas.change_cliente")
        return False


class ProdutoPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve"):
            return user.has_perm("produtos.view_produto")
        if action == "create":
            return user.has_perm("produtos.add_produto")
        if action in ("update", "partial_update"):
            return user.has_perm("produtos.change_produto")
        if action in ("destroy", "ativar", "desativar"):
            return user.has_perm("produtos.delete_produto")

        return False


class VendaPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve", "carne", "contrato", "recibo"):
            return user.has_perm("vendas.view_venda")
        if action == "create":
            return user.has_perm("vendas.add_venda")
        if action in ("update", "partial_update", "documentos", "trocar_produto", "gerar_link_contrato"):
            return user.has_perm("vendas.change_venda")
        if action in ("edicao_especial",):
            return user.has_perm("vendas.can_edit_imei_valores_venda")
        if action in ("cancelar",):
            return user.has_perm("vendas.change_venda")
        if action == "destroy":
            return user.has_perm("vendas.delete_venda")

        return False
    
    def has_object_permission(self, request, view, obj):
        """
        Verifica se o usuário tem acesso à venda específica.
        
        - Admin/staff: acesso total
        - Usuário com can_view_all_sales: acesso total
        - Outros: apenas vendas da(s) loja(s) vinculada(s)
        """
        user = request.user
        
        # Admin/staff tem acesso total
        if user.is_superuser or user.is_staff:
            return True
        
        # Usuários com permissão can_view_all_sales têm acesso total
        if user.has_perm("vendas.can_view_all_sales"):
            return True
        
        # Vendedores: apenas vendas das lojas vinculadas
        lojas_usuario = list(user.lojas.values_list('id', flat=True))
        
        # Adicionar loja principal se existir
        if hasattr(user, 'loja') and user.loja:
            lojas_usuario.append(user.loja.id)
        
        # Verificar se a venda pertence a alguma loja do usuário
        if obj.loja_id in lojas_usuario:
            return True
        
        return False


class UserPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Users can always read their own profile; administrative user
        # listings and detail views still require the accounts permission.
        if action == "me":
            return True
        if action in ("list", "retrieve"):
            return user.is_superuser or user.has_perm("accounts.view_user")
        if action == "create":
            return user.is_superuser or user.has_perm("accounts.add_user")
        if action in ("update", "partial_update"):
            return user.is_superuser or user.has_perm("accounts.change_user")
        if action == "destroy":
            return user.is_superuser or user.has_perm("accounts.delete_user")

        return False

    def has_object_permission(self, request, view, obj):
        """Quem não é superusuário só altera contas que não têm mais poder que a sua.

        Impede, por exemplo, que um gerente com `change_user` troque a senha ou o
        e-mail de um administrador da mesma loja e entre com a conta dele.
        """
        if request.method in SAFE_METHODS or request.user.is_superuser:
            return True
        if obj.is_superuser:
            return False
        return permissoes_da_conta(obj) <= request.user.get_all_permissions()


def codigos_de_permissao(permissoes) -> set[str]:
    """`app_label.codename` de um queryset/lista de `Permission`."""
    return {f"{p.content_type.app_label}.{p.codename}" for p in permissoes}


def permissoes_da_conta(user) -> set[str]:
    """Permissões diretas e dos grupos, mesmo com a conta inativa.

    (`get_all_permissions()` devolve vazio para inativo, o que deixaria
    reativar e assumir uma conta poderosa desativada.)
    """
    permissoes = Permission.objects.filter(Q(user=user) | Q(group__user=user)).select_related("content_type")
    return codigos_de_permissao(permissoes.distinct())


class GroupPermission(BasePermission):
    """Listar e ver grupos: qualquer autenticado. Criar/editar/excluir: permissão do `auth`."""

    PERMISSOES_ESCRITA = {
        "create": "auth.add_group",
        "update": "auth.change_group",
        "partial_update": "auth.change_group",
        "destroy": "auth.delete_group",
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        permissao = self.PERMISSOES_ESCRITA.get(getattr(view, "action", None))
        return bool(permissao) and user.has_perm(permissao)


class RepassePermission(BasePermission):
    """Permissões `financeiro.*_repasse` por ação.

    `agendados` (calendário calculado, aba "Agendados" do detalhe da loja na SPA
    do vendedor) continua aberta a qualquer autenticado, como antes; a view
    restringe a loja ao escopo do usuário.
    """

    PERMISSOES = {
        "list": "financeiro.view_repasse",
        "retrieve": "financeiro.view_repasse",
        "create": "financeiro.add_repasse",
        "update": "financeiro.change_repasse",
        "partial_update": "financeiro.change_repasse",
        "destroy": "financeiro.delete_repasse",
    }

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        action = getattr(view, "action", None)
        if action == "agendados":
            return True
        permissao = self.PERMISSOES.get(action)
        return bool(permissao) and user.has_perm(permissao)
