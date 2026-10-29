import os
import sys
import urllib.parse
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / '.env')
except ImportError:
    pass

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Core Environment & Security
DEBUG = os.environ.get('DJANGO_DEBUG', os.environ.get('DEBUG', 'True')).strip().lower() in ('true', '1', 'yes')

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "The SECRET_KEY environment variable must be set when DEBUG is False in production."
        )
    # Default insecure key for local development only
    SECRET_KEY = 'django-insecure-taskflow-saas-enterprise-key-2026-prod-grade'
elif not DEBUG and SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured(
        "A cryptographically secure SECRET_KEY without 'django-insecure-' prefix must be provided in production."
    )

ADMIN_REGISTRATION_CODE = os.environ.get('ADMIN_REGISTRATION_CODE', '')

# Allowed Hosts & CSRF Origins
allowed_hosts_env = os.environ.get('ALLOWED_HOSTS')
if allowed_hosts_env:
    ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_env.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Automatically include Render hostname if deployed on Render
render_hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)

csrf_origins_env = os.environ.get('CSRF_TRUSTED_ORIGINS')
if csrf_origins_env:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in csrf_origins_env.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []

if render_hostname:
    render_origin = f'https://{render_hostname}'
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

# Production Security Headers
if not DEBUG:
    # HTTPS redirection and cookies
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').strip().lower() in ('true', '1', 'yes')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # HTTP Strict Transport Security (HSTS)
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))  # Default 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True').strip().lower() in ('true', '1', 'yes')
    SECURE_HSTS_PRELOAD = os.environ.get('SECURE_HSTS_PRELOAD', 'True').strip().lower() in ('true', '1', 'yes')

    # Reverse proxy SSL header
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Security headers
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = 'DENY'

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party apps
    'rest_framework',

    # TaskFlow core apps
    'organizations.apps.OrganizationsConfig',
    'accounts.apps.AccountsConfig',
    'tasks.apps.TasksConfig',
    'notifications.apps.NotificationsConfig',
    'analytics.apps.AnalyticsConfig',
    'api.apps.ApiConfig',
    'ai_assistant.apps.AiAssistantConfig',
    'workflows.apps.WorkflowsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'organizations.middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'taskflow_core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'notifications.context_processors.notifications_context',
                'organizations.context_processors.organization_context',
                'tasks.context_processors.tasks_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'taskflow_core.wsgi.application'

# Database configuration: defaults to local SQLite, seamlessly supports PostgreSQL via DATABASE_URL or POSTGRES_* env vars
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    parsed_url = urllib.parse.urlparse(DATABASE_URL)
    if parsed_url.scheme in ('postgres', 'postgresql'):
        query_params = urllib.parse.parse_qs(parsed_url.query)
        db_options = {}
        if 'sslmode' in query_params:
            db_options['sslmode'] = query_params['sslmode'][0]

        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': parsed_url.path.lstrip('/'),
                'USER': urllib.parse.unquote(parsed_url.username or ''),
                'PASSWORD': urllib.parse.unquote(parsed_url.password or ''),
                'HOST': parsed_url.hostname or 'localhost',
                'PORT': parsed_url.port or 5432,
                'CONN_MAX_AGE': int(os.environ.get('CONN_MAX_AGE', '600')),
                'OPTIONS': db_options,
            }
        }
    elif parsed_url.scheme == 'sqlite':
        sqlite_rel_path = parsed_url.path.lstrip('/')
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / sqlite_rel_path if sqlite_rel_path else BASE_DIR / 'db.sqlite3',
                'OPTIONS': {'timeout': 20},
            }
        }
    else:
        raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {parsed_url.scheme}")
elif os.environ.get('POSTGRES_DB') or os.environ.get('DB_ENGINE') == 'postgresql':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'taskflow_db'),
            'USER': os.environ.get('POSTGRES_USER', 'taskflow_user'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': int(os.environ.get('POSTGRES_PORT') or 5432),
            'CONN_MAX_AGE': int(os.environ.get('CONN_MAX_AGE', '600')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 20,
            },
        }
    }

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 6},
    },
]

if "test" in sys.argv:
    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images) & WhiteNoise configuration
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_ROOT.mkdir(parents=True, exist_ok=True)

if "test" in sys.argv:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Authentication URLs
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# Google Gemini API configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-3.5-flash')
AI_ASSISTANT_MAX_ROUNDS = int(os.environ.get('TASKFLOW_AI_MAX_ROUNDS', 10))
AI_ASSISTANT_MAX_TOOL_CALLS = int(os.environ.get('TASKFLOW_AI_MAX_TOOL_CALLS', 20))

# Django REST Framework Settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# Messages framework bootstrap tag mapping
from django.contrib.messages import constants as messages
MESSAGE_TAGS = {
    messages.DEBUG: 'secondary',
    messages.INFO: 'info',
    messages.SUCCESS: 'success',
    messages.WARNING: 'warning',
    messages.ERROR: 'danger',
}

# Operational Logging Configuration
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': LOG_LEVEL,
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO').upper(),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'tasks': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'organizations': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'workflows': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'ai_assistant': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}
