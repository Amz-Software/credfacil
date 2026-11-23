from django.urls import path

from . import views

urlpatterns = [
    path('auth/csrf/', views.CsrfView.as_view(), name='csrf'),
    path('auth/login/', views.LoginView.as_view(), name='login'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('me/', views.MeView.as_view(), name='me'),
    path('me/senha/', views.TrocarSenhaView.as_view(), name='trocar-senha'),
]
