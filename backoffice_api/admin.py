from django.contrib import admin

from .models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ('criado_em', 'usuario_nome', 'acao', 'objeto_tipo', 'objeto_id', 'ip')
    list_filter = ('acao', 'objeto_tipo')
    search_fields = ('usuario_nome', 'objeto_id', 'descricao', 'motivo')
    date_hierarchy = 'criado_em'

    # Trilha de auditoria é só leitura, inclusive no admin.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
