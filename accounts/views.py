import json
from django import http
from django.contrib.auth.views import LoginView, logout_then_login, PasswordResetView,PasswordResetView, PasswordResetDoneView,PasswordResetConfirmView, PasswordResetCompleteView
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, ListView, CreateView
from vendas.models import Loja
from .forms import GroupForm, LoginForm, MyProfileForm, ResetPasswordForm
from django.views.generic.edit import UpdateView
from django.db.models import Q
from django.contrib.auth.models import Permission, Group
from .forms import UserForm
from .models import User
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView, PasswordChangeDoneView
from django.views.generic.edit import FormView

class LoginView(LoginView):
    template_name = 'login/login.html'
    authentication_form = LoginForm  

    def form_valid(self, form):
        # Capturar a loja do POST
        loja_id = self.request.POST.get('loja')
        user = form.get_user()

        # Validar se a loja é válida para o usuário
        if loja_id:
            try:
                loja = Loja.objects.get(id=loja_id, usuarios=user)
                self.request.session['loja_id'] = loja.id
            except Loja.DoesNotExist:
                messages.error(self.request, 'Loja inválida ou não permitida.')
                return redirect('accounts:login')
        
        return super().form_valid(form)

def logout_view(request):
    messages.success(request, 'Você saiu do sistema.')
    return logout_then_login(request)


class PasswordResetView(PasswordResetView):
    template_name = 'login/password_reset.html'
    email_template_name = 'login/password_reset_email.html'
    subject_template_name = 'login/password_reset_subject.txt'
    success_url = reverse_lazy('accounts:password_reset_done')
    title = 'Recuperar senha'

class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'login/password_reset_done.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'login/password_reset_confirm.html'

class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'login/password_reset_complete.html'
    

class ResetarSenhaView(FormView):
    template_name = 'login/resetar_senha.html'
    form_class = ResetPasswordForm
    success_url = reverse_lazy('accounts:my_profile_update')

    def form_valid(self, form):
        user = self.request.user
        password = form.cleaned_data.get('password')
        user.set_password(password)
        user.save()
        messages.success(self.request, 'Senha alterada com sucesso.')
        return super().form_valid(form)


class MyProfileView(TemplateView):
    template_name = 'profile/my_profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['lojas'] = Loja.objects.all()
        return context
    
    
class MyProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = MyProfileForm
    template_name = 'profile/my_profile_update.html'
    success_url = reverse_lazy('accounts:my_profile_update')

    def get_object(self):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, 'Perfil atualizado com sucesso.')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Erro ao atualizar o perfil. Verifique os dados informados.')
        return super().form_invalid(form)


class UserCreateView(CreateView):
    model = User
    form_class = UserForm
    template_name = 'user/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    permission_required = 'accounts.add_user'

    def form_valid(self, form):
        loja_id = self.request.session.get('loja_id')
        form.instance.loja = Loja.objects.get(id=loja_id)
        form.save()

        messages.success(self.request, 'Usuário criado com sucesso.')
        return super().form_valid(form)
    
    

class UserUpdateView(UpdateView):
    model = User
    form_class = UserForm
    template_name = 'user/user_form.html'
    success_url = reverse_lazy('accounts:user_list')
    permission_required = 'accounts.change_user'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['user'] = user
        return context


def delete_user(request, pk):
    user = User.objects.get(pk=pk)
    user.is_active = False
    user.save()
    messages.success(request, 'Usuário deletado com sucesso.')
    return redirect('accounts:user_list')


class PermissionsListView(ListView):
    model = Permission
    template_name = 'auth/permissions_list.html'
    context_object_name = 'permissions'
    permission_required = 'auth.view_permission'
    paginate_by = 10
    
    def get_queryset(self):
        query = super().get_queryset()

        search = self.request.GET.get('search', None)
        if search:
            query = query.filter(Q(name__icontains=search) | Q(content_type__app_label__icontains=search)| Q(codename__icontains=search))

        return query

class GroupListView(ListView):
    model = Group
    template_name = 'auth/groups_list.html'
    context_object_name = 'groups'
    permission_required = 'auth.view_group'
    paginate_by = 10
    
class GroupCreateView(CreateView):
    model = Group
    form_class = GroupForm
    template_name = 'auth/group_form.html'
    success_url = reverse_lazy('accounts:group_list')
    permission_required = 'auth.add_group'
    
class GroupUpdateView(UpdateView):
    model = Group
    form_class = GroupForm
    template_name = 'auth/group_form.html'
    success_url = reverse_lazy('accounts:group_list')
    permission_required = 'auth.change_group'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['group'] = self.object
        return context


class UserListView(ListView):
    model = User
    template_name = 'auth/users_list.html'
    context_object_name = 'users'
    permission_required = 'accounts.view_user'
    paginate_by = 10
    
    def get_queryset(self):
        query = super().get_queryset()
        loja_id = self.request.session.get('loja_id')
        my_user = self.request.user
        search = self.request.GET.get('search', None)
        if search:
            query = query.filter(Q(username__icontains=search) | Q(email__icontains=search))

        return query.filter(is_active=True).exclude(id=my_user.id).exclude(is_superuser=True).filter(loja=loja_id)
    
def get_lojas_by_username(request):
    username = request.GET.get('username')
    if not username:
        return http.JsonResponse({'error': 'Username não fornecido'}, status=400)

    try:
        user = User.objects.get(Q(username__iexact=username) | Q(email__iexact=username))
    except ObjectDoesNotExist:
        return http.JsonResponse({'error': 'Usuário não encontrado'}, status=404)
    except Exception:
        return http.JsonResponse({'error': 'Usuário não encontrado'}, status=404)

    lojas_qs = user.lojas.all()
    if lojas_qs.exists():
        lojas = [{'id': l.id, 'nome': l.nome} for l in lojas_qs]
    elif user.loja:
        lojas = [{'id': user.loja.id, 'nome': user.loja.nome}]
    else:
        lojas = []

    return http.JsonResponse({'lojas': lojas})
    
def get_autorizacao_user(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            username = data.get('username')
            password = data.get('password')
            loja_id = request.session.get('loja_id')

            if not username or not password:
                return http.JsonResponse({'success': False, 'message': 'Usuário ou senha não fornecidos.'}, status=400)

            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                return http.JsonResponse({'success': False, 'message': 'Usuário não encontrado.'}, status=404)

            if not user.check_password(password):
                return http.JsonResponse({'success': False, 'message': 'Usuário ou senha incorretos.'}, status=403)

            if loja_id:
                loja = Loja.objects.get(id=loja_id)
                if loja not in user.lojas_gerenciadas.all():
                    return http.JsonResponse({'success': False, 'message': 'Usuário não autorizado nesta loja.'}, status=403)

            return http.JsonResponse({'success': True, 'message': 'Autorizado.'}, status=200)

        except json.JSONDecodeError:
            return http.JsonResponse({'success': False, 'message': 'Dados inválidos no corpo da requisição.'}, status=400)

    return http.JsonResponse({'success': False, 'message': 'Método não permitido.'}, status=405)

            
