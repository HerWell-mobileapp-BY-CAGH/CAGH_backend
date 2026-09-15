import os
import sys
import json
from pathlib import Path
from datetime import timedelta


import dj_database_url


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / '.env')
except ImportError:
    pass

# Security & Debug Settings
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = 'django-insecure-cagh-backend-default-key-change-me'
    else:
        raise RuntimeError(
            "CRITICAL: SECRET_KEY environment variable is missing! "
            "Set a secure SECRET_KEY in your environment before deploying to production."
        )

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        'ALLOWED_HOSTS',
        'localhost,127.0.0.1,0.0.0.0,cagh-backend-api.onrender.com'
    ).split(',')
    if host.strip()
]



# Custom User Model & Authentication Backends
AUTH_USER_MODEL = 'users.User'
AUTHENTICATION_BACKENDS = [
    'apps.users.backends.EmailOrPhoneBackend',
    'django.contrib.auth.backends.ModelBackend',
]


# Application definition
INSTALLED_APPS = [
    # Django Core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third Party Apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # enables logout token blacklisting
    'drf_spectacular',
    'corsheaders',
    'channels',
    'django_filters',

    # CAGH Domain Apps
    'apps.users',
    'apps.midwives',
    'apps.appointments',
    'apps.consultations',
    'apps.chat',
    'apps.ai_assistant',
    'apps.learning',
    'apps.notifications',
    'apps.reviews',
    'apps.common',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.common.middleware.AuditLogMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

# Database
if 'test' in sys.argv:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'test_db.sqlite3',
        }
    }
elif os.environ.get('DATABASE_URL'):
    conn_max_age = int(os.environ.get('DB_CONN_MAX_AGE', os.environ.get('CONN_MAX_AGE', 0)))
    DATABASES = {
        'default': dj_database_url.config(
            conn_max_age=conn_max_age,
            conn_health_checks=True,
        )
    }
    if os.environ.get('DISABLE_SERVER_SIDE_CURSORS', '').lower() == 'true':
        DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
else:
    DB_NAME = os.environ.get('POSTGRES_DB', 'cagh_db')
    DB_USER = os.environ.get('POSTGRES_USER', 'cagh_user')
    DB_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
    if not DB_PASSWORD:
        if DEBUG:
            DB_PASSWORD = 'cagh_secure_password'
        else:
            raise RuntimeError(
                "CRITICAL: POSTGRES_PASSWORD environment variable (or DATABASE_URL) must be set in production!"
            )
    DB_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
    DB_PORT = os.environ.get('POSTGRES_PORT', '5432')

    conn_max_age = int(os.environ.get('DB_CONN_MAX_AGE', os.environ.get('CONN_MAX_AGE', 0)))
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': DB_NAME,
            'USER': DB_USER,
            'PASSWORD': DB_PASSWORD,
            'HOST': DB_HOST,
            'PORT': DB_PORT,
            'CONN_MAX_AGE': conn_max_age,
            'CONN_HEALTH_CHECKS': True,
        }
    }
    if os.environ.get('DISABLE_SERVER_SIDE_CURSORS', '').lower() == 'true':
        DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', 'English'),
    ('am', 'Amharic'),
]
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True
LOCALE_PATHS = [
    BASE_DIR / 'locale',
]



# Static & Media Files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'



MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'ai_chat': os.environ.get('AI_RATE_LIMIT', '20/minute'),
    },
}

# SimpleJWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', 60))),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=int(os.environ.get('JWT_REFRESH_TOKEN_LIFETIME_DAYS', 7))),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# DRF Spectacular / Swagger & OpenAPI Configuration
SPECTACULAR_SETTINGS = {
    'TITLE': 'CAGH Digital Midwife API',
    'DESCRIPTION': 'RESTful API and WebSocket backend organized in clean, logical mobile app user journey order.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api/v1/',
    'SECURITY': [{'Bearer': []}],
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
    },
    'POSTPROCESSING_HOOKS': [
        'apps.common.hooks.cagh_openapi_tag_postprocessor',
    ],
    'TAGS': [
        {'name': 'Splash & Languages', 'description': 'System Initialization, Languages, & Common Reference Data'},
        {'name': 'Auth & Security', 'description': 'Registration, OTP Verification, Login, & Password Recovery'},
        {'name': 'Users & Profiles', 'description': 'User Profile Management, Preferences, & Emergency Contacts'},
        {'name': 'Home & Learning', 'description': 'Home Dashboard Focus Areas, Educational Articles, & Topics'},
        {'name': 'Midwives & Consult Hub', 'description': 'Midwife Directory, Search, Profiles, Qualifications, & Admin Approvals'},
        {'name': 'Appointments', 'description': 'Appointment Scheduling & Management'},
        {'name': 'Consultations', 'description': 'Telemedicine Consultation Sessions'},
        {'name': 'Real-Time Chat', 'description': 'Direct Messaging & Real-Time Chat Channels'},
        {'name': 'AI Assistant', 'description': 'AI Healthcare Guidance & Chatbot Assistant'},
        {'name': 'Notifications', 'description': 'Push Notifications & Device Tokens'},
        {'name': 'Reviews & Ratings', 'description': 'Patient Reviews & Feedback'},
    ]
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:3000,http://127.0.0.1:3000'
    ).split(',')
    if origin.strip()
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://localhost(:\d+)?$",
    r"^http://127\.0\.0\.1(:\d+)?$",
    r"^http://192\.168\.\d+\.\d+(:\d+)?$",
    r"^http://10\.\d+\.\d+\.\d+(:\d+)?$",
]

_env_cors_regexes = os.environ.get('CORS_ALLOWED_ORIGIN_REGEXES', '').strip()
if _env_cors_regexes:
    CORS_ALLOWED_ORIGIN_REGEXES.extend(
        [r.strip() for r in _env_cors_regexes.split(',') if r.strip()]
    )

CORS_ALLOW_ALL_ORIGINS = False



# Channels Redis Layer
if 'test' in sys.argv:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }
else:
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                "hosts": [
                    {
                        "address": REDIS_URL,
                        "health_check_interval": 30,
                        "socket_keepalive": True,
                        "retry_on_timeout": True,
                        "socket_timeout": 15,
                        "socket_connect_timeout": 15,
                    }
                ],
            },
        },
    }

# Celery Configuration
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'

# ---------------------------------------------------------------------------
# Email Configuration
# ---------------------------------------------------------------------------
# In development this prints emails to the console instead of sending them.
# Switch to smtp.EmailBackend + SMTP credentials in production.
EMAIL_BACKEND = os.environ.get(
    'EMAIL_BACKEND',
    'apps.common.email.IPv4EmailBackend'
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 465))

if EMAIL_PORT == 465:
    EMAIL_USE_SSL = True
    EMAIL_USE_TLS = False
else:
    EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() == 'true'
    EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() == 'true'
    if EMAIL_USE_SSL and EMAIL_USE_TLS:
        EMAIL_USE_TLS = False
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER)

# ---------------------------------------------------------------------------
# Frontend URL (used in password reset emails)
# ---------------------------------------------------------------------------
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# Password reset token validity (seconds) — default 24 h
PASSWORD_RESET_TIMEOUT = int(os.environ.get('PASSWORD_RESET_TIMEOUT', 86400))

# ---------------------------------------------------------------------------
# Production Security Settings
# ---------------------------------------------------------------------------
if not DEBUG:
    # Trust Render / Reverse Proxy SSL headers
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = os.environ.get('SECURE_SSL_REDIRECT', 'True').lower() == 'true'
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', 31536000))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


# Google Maps API Key (Optional — used for dynamic Places API facility search)
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')

# WebRTC ICE Configuration
WEBRTC_STUN_SERVERS = json.loads(os.environ.get('WEBRTC_STUN_SERVERS', '["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"]'))
WEBRTC_TURN_SERVERS = json.loads(os.environ.get('WEBRTC_TURN_SERVERS', '[]'))




# Firebase Cloud Messaging & Admin SDK Configuration
FIREBASE_SERVICE_ACCOUNT_KEY = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY', os.path.join(BASE_DIR, 'firebase-service-account.json'))
GOOGLE_CLOUD_PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', 'cagh-bd916')

# AI Assistant Settings (Phase 1 Foundation)
AI_MAX_INPUT_LENGTH = int(os.environ.get('AI_MAX_INPUT_LENGTH', 1000))
AI_MAX_OUTPUT_TOKENS = int(os.environ.get('AI_MAX_OUTPUT_TOKENS', 1024))
AI_MAX_HISTORY_MESSAGES = int(os.environ.get('AI_MAX_HISTORY_MESSAGES', 6))
AI_KNOWLEDGE_CONTEXT_LIMIT = int(os.environ.get('AI_KNOWLEDGE_CONTEXT_LIMIT', 3))
