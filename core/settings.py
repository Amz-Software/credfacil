import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
# Build paths inside the project like this: BASE_DIR / 'subdir'.
import sentry_sdk


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv()


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
# DEBUG = os.environ.get('DEBUG', True)
DEBUG = True

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS').split(',') if os.environ.get('CSRF_TRUSTED_ORIGINS') else []

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True


if DEBUG:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'
    os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'accounts.apps.AccountsConfig',
    'financeiro.apps.FinanceiroConfig',
    'vendas.apps.VendasConfig',
    'produtos.apps.ProdutosConfig',
    'estoque.apps.EstoqueConfig',
    'assistencia.apps.AssistenciaConfig',
    'notificacao.apps.NotificacaoConfig',
    'api.apps.ApiConfig',
    'crispy_forms',
    'crispy_bootstrap5', 
    'redis',
    'django_select2',
    'notifications',
    'channels',
    'django.contrib.humanize',
    'rest_framework_simplejwt',
    'django_filters',
    'drf_spectacular',
    'corsheaders',
    'simple_history',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "accounts.middleware.LojaMiddleware",
    'simple_history.middleware.HistoryRequestMiddleware',
]

CACHES = {
    # … default cache config and others
    "select2": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:6379/2",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

ASGI_APPLICATION = 'core.asgi.application'
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}

# Tell select2 which cache configuration to use:
SELECT2_CACHE_BACKEND = "select2"

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
        'LOCATION': os.path.join(BASE_DIR, 'mediafiles'),
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.menu_items',
                'core.context_processors.loja',
                'core.context_processors.notificacoes_usuario',
            ],
        },
    },
]

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

WSGI_APPLICATION = 'core.wsgi.application'

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    },
    "select2": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{os.environ.get('REDIS_HOST')}:{os.environ.get('REDIS_PORT')}/{os.environ.get('REDIS_DB')}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

SELECT2_CACHE_BACKEND = "select2"

DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# Simple JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "CredFacil API",
    "DESCRIPTION": "Documentacao da API do sistema CredFacil.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# Database
# https://docs.djangoproject.com/en/5.1/ref/settings/#databases

DATABASES = {
    'sqlite': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    },
    'mysql': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get("DB_NAME"),
        'USER': os.environ.get("DB_USER"),
        'PASSWORD': os.environ.get("DB_PASSWORD"),
        'HOST': os.environ.get("DB_HOST"),
        'PORT': os.environ.get("DB_PORT"),
    },
}

db_used = os.environ.get('DB_USED')

# Set the default database to the one selected by DB_USED
DATABASES['default'] = DATABASES[db_used]


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOG_DIR = os.path.join(BASE_DIR, 'logs')
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,  
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',  
            'class': 'logging.FileHandler',
            'filename': os.path.join(LOG_DIR, 'django_debug.log'),
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',  
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': { 
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',  
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',  
            'propagate': False,
        },
        
        
    },
}

sentry_sdk.init(
    dsn="https://4f00ce347bbfc855105b131f702032b2@o4509403596062720.ingest.us.sentry.io/4510964474052608",
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=True,
)

# Internationalization
# https://docs.djangoproject.com/en/5.1/topics/i18n/

LANGUAGE_CODE = 'pt-br'
USE_L10N = True
TIME_ZONE = 'America/Belem'

USE_I18N = True

USE_TZ = True


AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'vendas:index'  

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.1/howto/static-files/

MEDIA_URL = '/mediafiles/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'mediafiles')

STATIC_URL = '/static/'
# Add these new lines
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'static'),
)

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]


# Default primary key field type
# https://docs.djangoproject.com/en/5.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
