# accounts/urls.py

from django.urls import path
from .views import *
from django.contrib.auth import views as auth_views


app_name = 'accounts'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', logout_view, name='logout'),
    path('buscar-lojas/', get_lojas_by_username, name='buscar_lojas'),
    # Recuperação de senha por e-mail (link com uidb64/token, público).
    path('password-reset/', PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    # Troca de senha do próprio usuário logado (tela do perfil).
    path('reset/', ResetarSenhaView.as_view(), name='resetar_senha'),
    
    path('profile/', MyProfileView.as_view(), name='profile'),
    
    path('gropos/', GroupListView.as_view(), name='group_list'),
    path('gropos/novo/', GroupCreateView.as_view(), name='group_create'),
    path('gropos/editar/<int:pk>/', GroupUpdateView.as_view(), name='group_update'),
    
    path('permissions/', PermissionsListView.as_view(), name='permissions_list'),
    # path('gropos/deletar/<int:pk>/', GroupDeleteView.as_view(), name='group_delete'),
    
    path('users/novo/', UserCreateView.as_view(), name='user_create'),
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/editar/<int:pk>/', UserUpdateView.as_view(), name='user_update'),
    path('users/deletar/<int:pk>/', delete_user, name='user_delete'),

    path('autorizacao/', get_autorizacao_user, name='autorizacao_user'),
    
    path('meu-perfil/', MyProfileUpdateView.as_view(), name='my_profile_update'),
    
    path('password_change/', auth_views.PasswordChangeView.as_view(template_name='auth/password_change_form.html'), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(template_name='auth/password_change_done.html'), name='password_change_done'),
]
