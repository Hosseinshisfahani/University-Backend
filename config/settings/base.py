from datetime import timedelta
from pathlib import Path

import environ

# backend/ directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="temporary-secret-key",
)

DEBUG = False

ALLOWED_HOSTS: list[str] = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
# Modular monolith: one Django project, isolated domain apps under apps/.

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.finance",
    "apps.notifications",
    "apps.institutes.psy_institute",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Custom user model — priority #1, must exist before the first migration.
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    # Outermost so Cache-Control is applied after the rest of the stack.
    "apps.core.middleware.DisableApiResponseCachingMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    # Before CommonMiddleware: restore trailing slash stripped by Next.js proxy.
    "apps.core.middleware.ForceApiTrailingSlashMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database — centralized PostgreSQL, configured via DATABASE_URL
# ---------------------------------------------------------------------------

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://etrat:etrat@127.0.0.1:5432/etrat",
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/django-static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "University Platform API",
    "DESCRIPTION": "REST API for the university platform (modular monolith).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# JWT — issued exclusively as HttpOnly cookies (XSS prevention).
# Tokens are never returned in JSON bodies and never readable by JavaScript.
# ---------------------------------------------------------------------------

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}

JWT_ACCESS_COOKIE = "etrat_access"
JWT_REFRESH_COOKIE = "etrat_refresh"
JWT_COOKIE_SECURE = env.bool("JWT_COOKIE_SECURE", default=True)
JWT_COOKIE_SAMESITE = "Lax"
# The refresh cookie is path-scoped so it is only ever sent to the auth
# endpoints (refresh/logout), never with regular API requests.
JWT_REFRESH_COOKIE_PATH = "/api/v1/auth/"

# ---------------------------------------------------------------------------
# CORS / CSRF — cookie-based auth requires credentialed requests with an
# explicit origin allowlist (wildcards are incompatible with credentials).
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
# API client sends these so the edge CDN will not replay a stale GET.
CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "cache-control",
    "pragma",
)

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ---------------------------------------------------------------------------
# Finance
# ---------------------------------------------------------------------------
# Amounts are IRR (Rials) with 0 decimal places. Toman UI conversion is frontend-only.
FINANCE_CURRENCY = "IRR"

# ---------------------------------------------------------------------------
# Vandar IPG
# ---------------------------------------------------------------------------
# Callback and browser return URLs come only from the environment so staging,
# QA, and tunnels can set their own hosts without a code change.
VANDAR_SANDBOX_MODE = env.bool("VANDAR_SANDBOX_MODE", default=True)
VANDAR_API_KEY = env("VANDAR_API_KEY", default="")
VANDAR_CALLBACK_URL = env("VANDAR_CALLBACK_URL", default="")
VANDAR_FRONTEND_SUCCESS_URL = env("VANDAR_FRONTEND_SUCCESS_URL", default="")
VANDAR_FRONTEND_FAILURE_URL = env("VANDAR_FRONTEND_FAILURE_URL", default="")
VANDAR_SEND_URL = env(
    "VANDAR_SEND_URL",
    default="https://ipg.vandar.io/api/v4/send",
)
VANDAR_REDIRECT_BASE_URL = env(
    "VANDAR_REDIRECT_BASE_URL",
    default="https://ipg.vandar.io/v4",
)
VANDAR_VERIFY_URL = env(
    "VANDAR_VERIFY_URL",
    default="https://ipg.vandar.io/api/v4/verify",
)
VANDAR_TRANSACTION_URL = env(
    "VANDAR_TRANSACTION_URL",
    default="https://ipg.vandar.io/api/v4/transaction",
)


# ---------------------------------------------------------------------------
# SMS (SSMSS REST)
# ---------------------------------------------------------------------------
SMS_SANDBOX_MODE = env.bool("SMS_SANDBOX_MODE", default=True)
SSMSS_API_KEY = env("SSMSS_API_KEY", default="")
SSMSS_SENDER_NUMBER = env("SSMSS_SENDER_NUMBER", default="")
SSMSS_BASE_URL = env(
    "SSMSS_BASE_URL",
    default="http://ssmss.ir/webservice/rest",
)