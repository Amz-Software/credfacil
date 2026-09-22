"""Ações de exclusão em massa no admin, pensadas para limpeza por loja.

A ação padrão "Remover selecionados" monta a árvore completa de objetos
relacionados na tela de confirmação. Ao limpar todas as solicitações ou vendas
de uma loja isso gera milhares de linhas e a página trava. Esta ação troca a
árvore por contagens agregadas e apaga em lotes.
"""

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.db import DatabaseError, transaction
from django.db.models import ProtectedError
from django.db.models.deletion import Collector
from django.template.response import TemplateResponse

CAMPO_CONFIRMACAO = 'confirmar_exclusao_em_massa'
NOME_ACAO = 'excluir_em_massa'
TEMPLATE_CONFIRMACAO = 'admin/vendas/exclusao_em_massa.html'
LIMITE_PREVIA_DETALHADA = 2000
TAMANHO_LOTE = 500
MAX_ERROS_EXIBIDOS = 5


def _contar_em_cascata(queryset):
    """Conta, por modelo, tudo que será removido em cascata pelo queryset."""
    collector = Collector(using=queryset.db)
    collector.collect(queryset)

    contagens = {}
    for modelo, objetos in collector.data.items():
        if objetos:
            contagens[modelo] = contagens.get(modelo, 0) + len(objetos)
    for queryset_rapido in collector.fast_deletes:
        total = queryset_rapido.count()
        if total:
            modelo = queryset_rapido.model
            contagens[modelo] = contagens.get(modelo, 0) + total

    linhas = [
        (str(modelo._meta.verbose_name_plural), total)
        for modelo, total in contagens.items()
    ]
    return sorted(linhas, key=lambda linha: -linha[1])


def _lojas_afetadas(queryset):
    """Nomes distintos das lojas presentes na seleção."""
    nomes = queryset.order_by().values_list('loja__nome', flat=True).distinct()
    return sorted(nome or 'Sem loja' for nome in nomes)


def _excluir_em_lotes(modelo, pks):
    """Apaga os pks em lotes independentes e devolve (total_apagado, erros)."""
    total_apagado = 0
    erros = []
    for inicio in range(0, len(pks), TAMANHO_LOTE):
        lote = pks[inicio:inicio + TAMANHO_LOTE]
        try:
            with transaction.atomic():
                _, detalhes = modelo.objects.filter(pk__in=lote).delete()
            total_apagado += detalhes.get(modelo._meta.label, 0)
        except (ProtectedError, DatabaseError) as erro:
            erros.append(str(erro))
    return total_apagado, erros


def _pagina_confirmacao(modeladmin, request, queryset, total):
    opts = modeladmin.model._meta
    contagens = _contar_em_cascata(queryset) if total <= LIMITE_PREVIA_DETALHADA else []
    contexto = {
        **modeladmin.admin_site.each_context(request),
        'title': f'Confirmar exclusão de {opts.verbose_name_plural}',
        'opts': opts,
        'total': total,
        'contagens': contagens,
        'limite_previa': LIMITE_PREVIA_DETALHADA,
        'lojas': _lojas_afetadas(queryset),
        'selecionados': request.POST.getlist(helpers.ACTION_CHECKBOX_NAME),
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        'nome_acao': NOME_ACAO,
        'campo_confirmacao': CAMPO_CONFIRMACAO,
        'select_across': request.POST.get('select_across', '0'),
        'index': request.POST.get('index', '0'),
        'media': modeladmin.media,
    }
    return TemplateResponse(request, TEMPLATE_CONFIRMACAO, contexto)


@admin.action(
    description='🗑️ Excluir em massa (limpeza por loja)',
    permissions=['delete'],
)
def excluir_em_massa(modeladmin, request, queryset):
    """Exclui a seleção inteira sem montar a árvore de objetos relacionados."""
    modelo = modeladmin.model
    pks = list(queryset.order_by().values_list('pk', flat=True))
    if not pks:
        modeladmin.message_user(request, 'Nenhum registro selecionado.', messages.WARNING)
        return None

    if not request.POST.get(CAMPO_CONFIRMACAO):
        return _pagina_confirmacao(modeladmin, request, queryset, len(pks))

    total_apagado, erros = _excluir_em_lotes(modelo, pks)
    if total_apagado:
        modeladmin.message_user(
            request,
            f'{total_apagado} {modelo._meta.verbose_name_plural} excluídos '
            f'(inclui os registros relacionados em cascata).',
            messages.SUCCESS,
        )
    for erro in erros[:MAX_ERROS_EXIBIDOS]:
        modeladmin.message_user(request, f'Falha ao excluir um lote: {erro}', messages.ERROR)
    if len(erros) > MAX_ERROS_EXIBIDOS:
        modeladmin.message_user(
            request, f'…e mais {len(erros) - MAX_ERROS_EXIBIDOS} lote(s) com falha.', messages.ERROR
        )
    return None
