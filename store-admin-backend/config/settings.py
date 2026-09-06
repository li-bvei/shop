"""
Django settings for config project.
"""

from datetime import timedelta
from pathlib import Path

import environ
from corsheaders.defaults import default_headers as cors_default_headers

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY', default='django-insecure-change-me-in-production')

DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])

# Served behind an outer nginx (宝塔) that terminates TLS and proxies plain
# HTTP inward — trust its X-Forwarded-Proto so request.is_secure(),
# SECURE_SSL_REDIRECT and the CSRF Origin check know the request was HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Django admin (session + CSRF) over HTTPS needs the site's own https://
# origin listed here. The JWT API doesn't use CSRF, so this only matters
# for /admin/. Empty in local dev.
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'corsheaders',
    'organizations',
    'accounts',
    'branches',
    'staff',
    'paymentmethods',
    'dailyreports',
    'purchasing',
    'dashboard',
    'scheduling',
    'wages',
    'inventory',
    'lottery',
    'promotions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'common.middleware.OrganizationFeatureGateMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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


# Database
# Uses MySQL via PyMySQL (pure-Python driver, no native build toolchain needed).
# See config/__init__.py for the pymysql.install_as_MySQLdb() shim.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': env('DB_NAME', default='store_admin'),
        'USER': env('DB_USER', default='root'),
        'PASSWORD': env('DB_PASSWORD', default=''),
        'HOST': env('DB_HOST', default='127.0.0.1'),
        'PORT': env('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}

AUTH_USER_MODEL = 'accounts.User'


# Cache — a database-backed shared cache (no extra container). The
# promotions app's phase-3 rate limiting needs a cache that's shared
# across gunicorn workers, which the default LocMemCache is not. The
# `promotions_cache_table` is created by promotions migration 0002
# (RunPython -> createcachetable), so a fresh `migrate` sets it up with
# no extra deploy step.

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
        'LOCATION': 'promotions_cache_table',
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Django REST Framework

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
        'common.permissions.DenyStaffRole',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    # No pagination — the frontend fetches full lists and filters/sorts
    # client-side (matching how the mock layer it's replacing behaved).
    # Revisit if any list grows large enough to make that impractical.
    'DEFAULT_PAGINATION_CLASS': None,
    # No DEFAULT_THROTTLE_CLASSES — throttling applies only where a view
    # opts in (currently the promotions public guest endpoints). Rates are
    # counted in the shared DB cache (see CACHES). See
    # promotions/throttling.py.
    'DEFAULT_THROTTLE_RATES': {
        'promo_guest_read': '120/min',
        'promo_guest_write': '20/min',
        'promo_staff_verify': '40/min',
    },
}

# promotions APPI retention — customers with no activity for this many
# months are erased by `manage.py purge_stale_promotion_customers`.
PROMOTIONS_CUSTOMER_RETENTION_MONTHS = env.int('PROMOTIONS_CUSTOMER_RETENTION_MONTHS', default=24)

# How many reverse proxies sit in front of Django, for promotions.utils.
# client_ip (guest-endpoint throttling + risk trail). 1 = just our nginx;
# set 0 if Django is exposed directly so a spoofed X-Forwarded-For can't
# mint throttle buckets.
PROMOTIONS_TRUSTED_PROXY_COUNT = env.int('PROMOTIONS_TRUSTED_PROXY_COUNT', default=1)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}


# CORS - the Vite dev server for store-admin-frontend

CORS_ALLOWED_ORIGINS = env.list(
    'CORS_ALLOWED_ORIGINS',
    default=[
        'http://localhost:5173',
        'http://localhost:5174',
        'http://localhost:5175',
        'http://127.0.0.1:5173',
    ],
)
CORS_ALLOW_CREDENTIALS = True

# The public guest card client sends its card_token in this header when the
# dev frontend and API are on different ports (no shared cookie). Same-origin
# production uses the pc_guest cookie and never needs this.
CORS_ALLOW_HEADERS = (*cors_default_headers, 'x-guest-token')


# Deploy-time security settings — every one of these defaults to the
# insecure/off value that plain HTTP local development needs, and every one
# is meant to be flipped on via the production .env once the site is served
# over HTTPS behind a real hostname. `python manage.py check --deploy` will
# keep warning about all four (plus SECRET_KEY strength, which has no safe
# default value to fall back to) until they're set for that environment —
# see store-admin-backend/README.md for the full list.
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=False)
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=False)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=False)
SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)

# The public guest card cookie (promotions app) — Secure in production so
# it only travels over HTTPS. Defaults to `not DEBUG`: local cross-port
# dev (Vite on 5173/5175, API on 8071) can't share the cookie anyway and
# uses the X-Guest-Token header instead, so a non-Secure cookie there is
# harmless.
GUEST_COOKIE_SECURE = env.bool('GUEST_COOKIE_SECURE', default=not DEBUG)
