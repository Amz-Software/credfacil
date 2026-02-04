from rest_framework.permissions import BasePermission


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
        if action == "destroy":
            return user.has_perm("vendas.delete_loja")

        return False


class SolicitacaoCreditoPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if action in ("list", "retrieve", "kpis"):
            return user.has_perm("vendas.view_cliente")
        if action == "create":
            return user.has_perm("vendas.add_cliente")
        if action in ("update", "partial_update", "imei_telefone"):
            return user.has_perm("vendas.change_cliente")
        if action in ("aprovar", "reprovar", "cancelar", "status_app", "confirmar_app", "instalar_app"):
            return user.has_perm("vendas.change_status_analise") or user.has_perm("vendas.change_cliente")
        if action == "destroy":
            return user.has_perm("vendas.delete_cliente")

        return False
