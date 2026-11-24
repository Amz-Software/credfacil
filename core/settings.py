import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
# Build paths inside the project like this: BASE_DIR / 'subdir'.
import sentry_sdk


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv()


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
def _env_bool(nome: str, padrao: bool = False) -> bool:
    valor = os.environ.get(nome)
    if valor is None or valor.strip() == '':
        return padrao
    return valor.strip().lower() in ('1', 'true', 'yes', 'sim', 'on')


def _env_lista(nome: str, padrao: str = '') -> list[str]:
    return [item.strip() for item in os.environ.get(nome, padrao).split(',') if item.strip()]


_RODANDO_TESTES = len(sys.argv) > 1 and sys.argv[1] == 'test'

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if not _RODANDO_TESTES:
        raise ImproperlyConfigured('Defina a variável de ambiente SECRET_KEY.')
    SECRET_KEY = 'chave-somente-para-testes'

# DEBUG só liga com DEBUG=True no ambiente; o padrão é desligado (produção).
DEBUG = _env_bool('DEBUG', False)

ALLOWED_HOSTS = _env_lista('ALLOWED_HOSTS', 'localhost,127.0.0.1')
CSRF_TRUSTED_ORIGINS = _env_lista('CSRF_TRUSTED_ORIGINS')

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
    'crm.apps.CrmConfig',
    'rest_framework_simplejwt.token_blacklist',
    'axes',
    'backoffice_api.apps.BackofficeApiConfig',
    'pagamentos_online.apps.PagamentosOnlineConfig',
]

# CRM de WhatsApp: tarefas de fundo (envio de mídia, processamento) rodam em threads
# depois do commit; True roda na hora (testes e o comando crm_rotinas).
CRM_TAREFAS_SINCRONAS = os.environ.get('CRM_TAREFAS_SINCRONAS', 'False').lower() == 'true'

MIDDLEWARE = [
    'core.middleware.HealthCheckMiddleware',  # primeiro: liveness sem host/sessão/banco
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.LoginObrigatorioMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "accounts.middleware.LojaMiddleware",
    'simple_history.middleware.HistoryRequestMiddleware',
    # Por último, como pede o django-axes: bloqueia login após falhas seguidas.
    'axes.middleware.AxesMiddleware',
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Bloqueio por tentativas (django-axes): 5 falhas em 15 min por usuário + IP.
AXES_ENABLED = _env_bool('AXES_ENABLED', not _RODANDO_TESTES)
AXES_FAILURE_LIMIT = int(os.environ.get('AXES_FAILURE_LIMIT', '5'))
AXES_COOLOFF_TIME = timedelta(minutes=int(os.environ.get('AXES_COOLOFF_MINUTOS', '15')))
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_FORM_FIELD = 'username'
AXES_IPWARE_PROXY_COUNT = int(os.environ.get('AXES_PROXY_COUNT', '1'))
AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR']
AXES_LOCKOUT_CALLABLE = 'core.seguranca.resposta_bloqueio_login'

# Redis: um único endereço para o cache do select2 e para o channel layer.
REDIS_HOST = os.environ.get('REDIS_HOST') or 'redis'
REDIS_PORT = os.environ.get('REDIS_PORT') or '6379'
REDIS_DB = os.environ.get('REDIS_DB') or '0'
# Senha do Redis (docker-compose sobe o Redis com --requirepass); vazia = sem senha.
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')
_REDIS_CREDENCIAL = f":{quote(REDIS_PASSWORD, safe='')}@" if REDIS_PASSWORD else ''
REDIS_URL = f"redis://{_REDIS_CREDENCIAL}{REDIS_HOST}:{REDIS_PORT}"

ASGI_APPLICATION = 'core.asgi.application'
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            # Timeouts evitam conexão "zumbi" com o Redis travando envios sem fim
            # (incidente de 2026-11-12). socket_timeout > brpop_timeout (5s) do
            # channels_redis, para não derrubar a leitura bloqueante do consumer.
            "hosts": [{
                "address": REDIS_URL,
                "socket_connect_timeout": 3,
                "socket_timeout": 15,
                "socket_keepalive": True,
                "health_check_interval": 30,
            }],
        },
    },
}

# PagBank (pagamentos_online): token só no ambiente. PAGBANK_AMBIENTE = sandbox | producao.
PAGBANK_TOKEN = os.environ.get('PAGBANK_TOKEN', '')
PAGBANK_AMBIENTE = os.environ.get('PAGBANK_AMBIENTE', 'sandbox').strip().lower()
PAGBANK_TIMEOUT = float(os.environ.get('PAGBANK_TIMEOUT', '20'))
if PAGBANK_AMBIENTE not in ('sandbox', 'producao'):
    raise ImproperlyConfigured("PAGBANK_AMBIENTE deve ser 'sandbox' ou 'producao'.")

# Envio WS de notificações: timeout por envio (s).
NOTIFICACAO_WS_TIMEOUT = float(os.environ.get("NOTIFICACAO_WS_TIMEOUT", "3"))

# Mídia local: URL assinada e com validade (core/midia.py); sem a assinatura
# certa, /mediafiles/ responde 404. Com MIDIA_X_ACCEL_PREFIXO (ex.: /_midia/), o
# Django só confere a assinatura e o nginx entrega o arquivo de um `location internal`.
MIDIA_ASSINATURA_HORAS = int(os.environ.get('MIDIA_ASSINATURA_HORAS', '6'))
MIDIA_X_ACCEL_PREFIXO = os.environ.get('MIDIA_X_ACCEL_PREFIXO', '').strip()

STORAGES = {
    'default': {
        'BACKEND': 'core.midia.MidiaAssinadaStorage',
        'LOCATION': os.path.join(BASE_DIR, 'mediafiles'),
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}

# Mídia no S3 (bucket privado, URLs assinadas). Credenciais via AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY no ambiente. As chaves no bucket são os mesmos nomes gravados
# nos FileFields (sem prefixo), então os registros existentes continuam válidos.
USE_S3 = os.environ.get('USE_S3', 'False').lower() == 'true'
if USE_S3:
    STORAGES['default'] = {'BACKEND': 'storages.backends.s3.S3Storage'}
    # Falha já na inicialização se faltar configuração, em vez de 500 no primeiro upload.
    for _var in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_STORAGE_BUCKET_NAME'):
        if not os.environ.get(_var):
            raise ImproperlyConfigured(f'USE_S3=True exige a variável {_var}')
    AWS_STORAGE_BUCKET_NAME = os.environ['AWS_STORAGE_BUCKET_NAME']
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'sa-east-1')
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_S3_ADDRESSING_STYLE = 'virtual'
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = int(os.environ.get('AWS_QUERYSTRING_EXPIRE', 12 * 60 * 60))
    # Vários uploads usam pastas planas com o nome original do arquivo: nunca sobrescrever.
    AWS_S3_FILE_OVERWRITE = False

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
        "LOCATION": f"{REDIS_URL}/{REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

# Cache usado pelos widgets do django-select2.
SELECT2_CACHE_BACKEND = "select2"
# Contadores de segurança do assistente de IA do CRM (tentativas por CPF): precisam ser
# compartilhados entre os processos web e crm-worker, por isso no Redis.
CRM_CACHE_LIMITES = os.environ.get('CRM_CACHE_LIMITES', 'select2')

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
    # Limites por escopo; as views públicas e de login declaram o próprio escopo.
    # Na suíte de testes os limites ficam altos (o cache persiste entre os testes).
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.environ.get("THROTTLE_ANON", "60/min") if not _RODANDO_TESTES else "10000/min",
        "user": os.environ.get("THROTTLE_USER", "600/min") if not _RODANDO_TESTES else "10000/min",
        "login": os.environ.get("THROTTLE_LOGIN", "10/min") if not _RODANDO_TESTES else "10000/min",
        "publico": os.environ.get("THROTTLE_PUBLICO", "20/min") if not _RODANDO_TESTES else "10000/min",
    },
    # IP do cliente para os limites = salto do proxy confiável no X-Forwarded-For
    # (sem isso o DRF usa o cabeçalho inteiro, que o cliente pode variar à vontade).
    "NUM_PROXIES": AXES_IPWARE_PROXY_COUNT,
}

# Simple JWT
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    # Rotação fica desligada até a SPA do vendedor gravar o refresh novo
    # (front-connect-magic/src/lib/api.ts regrava o antigo). A blacklist já
    # serve para o logout invalidar o refresh no servidor.
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

def _timeouts_mysql() -> dict:
    """Timeouts do cliente MySQL vindos do ambiente; valor 0 omite a opção."""
    padroes = {'connect_timeout': '10', 'read_timeout': '120', 'write_timeout': '120'}
    valores = {
        opcao: int(os.environ.get(f"DB_{opcao.upper()}", padrao))
        for opcao, padrao in padroes.items()
    }
    return {opcao: valor for opcao, valor in valores.items() if valor > 0}


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
        # Nenhuma query pode esperar para sempre (incidente de 2026-11-12).
        # Valores em segundos; 0 desliga (o deploy usa 0 no `migrate`, para um
        # ALTER TABLE longo não ser cortado no meio).
        # utf8mb4 na conexão: sem isso o driver usa utf8mb3 e qualquer emoji (WhatsApp) falha ao gravar.
        'OPTIONS': {**_timeouts_mysql(), 'charset': 'utf8mb4'},
    },
}

# DB_USED escolhe o banco ('sqlite' ou 'mysql'); sem a variável, usa sqlite.
db_used = os.environ.get('DB_USED') or 'sqlite'
if db_used not in DATABASES:
    raise ImproperlyConfigured(f"DB_USED inválido: {db_used!r} (use 'sqlite' ou 'mysql')")
DATABASES['default'] = DATABASES[db_used]


# Password validation
# https://docs.djangoproject.com/en/5.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 10},
    },
    {
        'NAME': 'accounts.validators.SenhaForteValidator',
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

# Sentry: DSN pelo ambiente (o valor antigo fica como padrão para não quebrar o
# deploy atual); SENTRY_DSN vazio desliga. Dados pessoais (IP, cookies, cabeçalhos)
# só vão para o Sentry com SENTRY_SEND_DEFAULT_PII=True.
_SENTRY_DSN_PADRAO = (
    "https://4f00ce347bbfc855105b131f702032b2@o4509403596062720.ingest.us.sentry.io/4510964474052608"
)
SENTRY_DSN = os.environ.get('SENTRY_DSN', _SENTRY_DSN_PADRAO)
SENTRY_SEND_DEFAULT_PII = os.environ.get('SENTRY_SEND_DEFAULT_PII', 'False').lower() == 'true'
# A suíte de testes (manage.py test) não envia eventos para o Sentry de produção.
if SENTRY_DSN and not _RODANDO_TESTES:
    sentry_sdk.init(dsn=SENTRY_DSN, send_default_pii=SENTRY_SEND_DEFAULT_PII)

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
# Mídia do CRM de WhatsApp sem S3: fora do MEDIA_ROOT, que é servido publicamente.
CRM_MIDIA_ROOT = os.environ.get('CRM_MIDIA_ROOT', os.path.join(BASE_DIR, 'mediafiles_privado'))

STATIC_URL = '/static/'
# Add these new lines
STATICFILES_DIRS = (
    os.path.join(BASE_DIR, 'static'),
)

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# CORS: só as origens configuradas (SPA do vendedor; o backoffice novo usa
# proxy reverso no próprio domínio e não depende de CORS).
CORS_ALLOWED_ORIGINS = _env_lista('CORS_ALLOWED_ORIGINS')
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

# E-mail: SMTP quando EMAIL_HOST estiver definido; senão, console (desenvolvimento).
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
    EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', True)
    DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# --------------------------------------------------------------------------
# Cookies e cabeçalhos de segurança
# --------------------------------------------------------------------------
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = _env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
X_FRAME_OPTIONS = 'DENY'
# HSTS só pelo ambiente (ligar depois de confirmar HTTPS em todos os domínios).
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', False)

# Esquema OpenAPI e Swagger só para staff.
SPECTACULAR_SETTINGS['SERVE_PERMISSIONS'] = ['rest_framework.permissions.IsAdminUser']

# --------------------------------------------------------------------------
# Backoffice React (SPA em outro domínio, com proxy reverso para /api/bo/ e /ws/)
# --------------------------------------------------------------------------
# URL pública da SPA (ex.: https://painel.exemplo.com.br), usada nos redirecionamentos.
BACKOFFICE_SPA_URL = os.environ.get('BACKOFFICE_SPA_URL', '').rstrip('/')
# Módulos cujas telas Django redirecionam para a SPA (ex.: "credito,vendas").
BACKOFFICE_SPA_MODULOS = set(_env_lista('BACKOFFICE_SPA_MODULOS'))
# Sessão do backoffice: expira por inatividade e tem limite absoluto.
BACKOFFICE_SESSAO_INATIVIDADE_MIN = int(os.environ.get('BACKOFFICE_SESSAO_INATIVIDADE_MIN', '30'))
BACKOFFICE_SESSAO_MAXIMA_HORAS = int(os.environ.get('BACKOFFICE_SESSAO_MAXIMA_HORAS', '12'))
