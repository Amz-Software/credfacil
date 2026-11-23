from django.views.generic import ListView
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, get_object_or_404
from notifications.models import Notification
from django.views import View
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views.generic import ListView
from django.db.models import Q
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import RedirectView
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

@login_required
def marcar_como_lida(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.mark_as_read()
    return redirect(notif.target.get_absolute_url() if notif.target else '/')


@require_POST
@login_required
def marcar_todas_como_lidas(request):
    request.user.notifications.mark_all_as_read()
    return redirect('vendas:index')


@method_decorator(login_required, name='dispatch')
class MarcarNotificacaoComoLidaView(View):
    def post(self, request, pk):
        notificacao = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notificacao.mark_as_read()
        return JsonResponse({'status': 'ok'})


class NotificacaoListView(LoginRequiredMixin, ListView):
    model = Notification
    template_name = 'lista_notificacoes.html'
    context_object_name = 'notificacoes'
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user
        qs = Notification.objects.filter(recipient=user)
        search = self.request.GET.get('search')
        status = self.request.GET.get('status')
        if search:
            qs = qs.filter(Q(verb__icontains=search) | Q(description__icontains=search))
        if status == 'nao_lida':
            qs = qs.filter(unread=True)
        elif status == 'lida':
            qs = qs.filter(unread=False)
        return qs.order_by('-timestamp')

    def post(self, request, *args, **kwargs):
        # IDs vindos do form
        ids = request.POST.getlist('selected_notifications')
        if ids:
            # Apenas as do usuário e que estejam não lidas
            notifs = Notification.objects.filter(
                recipient=request.user,
                id__in=ids,
                unread=True
            )
            # marca todas como lidas
            notifs.update(unread=False)
        # volta pra mesma página, preservando filtros de GET
        params = request.GET.urlencode()
        url = request.path
        if params:
            url += f'?{params}'
        return redirect(url)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.request.GET.get('search', '')
        context['status'] = self.request.GET.get('status', '')
        return context



class MarcarNotificacaoComoLidaRedirectView(LoginRequiredMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        pk = kwargs['pk']
        notif = get_object_or_404(Notification, pk=pk, recipient=self.request.user)
        notif.mark_as_read()  # marca como lida
        # pega o destino: parâmetro next (só do próprio site) ou o próprio target
        destino = self.request.GET.get('next')
        if destino and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure(),
        ):
            return destino
        return notif.target.get_absolute_url()
    
    

@login_required
def marcar_selecionadas(request):
    if request.method == 'POST':
        ids = request.POST.getlist('selected_notifications')
        if ids:
            # marca apenas as não-lidas dentre as selecionadas
            request.user.notifications.unread().filter(id__in=ids).mark_all_as_read()
    return redirect(_proxima_pagina(request))


@login_required
def ler_todas(request):
    if request.method == 'POST':
        request.user.notifications.unread().mark_all_as_read()
    return redirect(_proxima_pagina(request))


def _proxima_pagina(request):
    """`next` (ou a página de origem), só se for do próprio site: sem redirecionamento aberto."""
    destino = request.GET.get('next') or request.POST.get('next') or request.META.get('HTTP_REFERER')
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return destino
    return 'notificacao_list'