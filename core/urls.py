"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from api.views import CustomTokenObtainPairView, LogoutJwtView, foto_celular_view
from core.midia import servir_midia
from crm.web.publico import politica_privacidade
from crm.webhook import WebhookWhatsAppView

urlpatterns = []

if not settings.USE_S3:
    # Mídia local só com URL assinada (core/midia.py); antes da lista para não
    # cair em nenhuma rota dos apps.
    urlpatterns += [
        path(f"{settings.MEDIA_URL.strip('/')}/<path:caminho>", servir_midia, name='midia'),
    ]

urlpatterns += [
    path('admin/', admin.site.urls),
    path("select2/", include("django_select2.urls")),
    path('', include('vendas.urls')),
    path('', include('produtos.urls')),
    path('', include('estoque.urls')),
    path('', include('financeiro.urls')),
    path('', include('accounts.urls')),
    path('notificacao/', include('notificacao.urls')),
    path('foto/<uuid:session_id>/', foto_celular_view, name='foto-celular'),
    path('api/whatsapp/webhook/', WebhookWhatsAppView.as_view(), name='whatsapp-webhook'),
    path('crm/', include('crm.web.urls')),
    path('privacidade/', politica_privacidade, name='politica_privacidade'),
    path('api/bo/v1/', include('backoffice_api.urls', namespace='backoffice_api')),
    path('api/', include('api.urls')),
    path('api/token/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/token/logout/', LogoutJwtView.as_view(), name='token_logout'),
    path('api/schema/', SpectacularAPIView.as_view(), name='api-schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
]

