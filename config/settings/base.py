"""
Configurações base do FocusBarber — compartilhadas por todos os ambientes.
Diretrizes PRD:
  - §13.2 Segurança por design / multi-tenant (tenant_id em todas queries)
  - §13.5 Static files: collectstatic sempre com --clear
  - §13.6 Segredos: nenhum segredo versionado; .env via environs (gitignored)
  - §13.1 Reactivity/UX: respeitar design system (design-system.html)
"""
import os
from pathlib import Path

import dj_database_url
from environs import Env

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ---------- Environment ----------
env = Env()
env.read_env(os.path.join(BASE_DIR, ".env"))

# ---------- Core ----------
SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "0.0.0.0"])

# ---------- Apps ----------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "base.apps.BaseConfig",
    "core.apps.CoreConfig",
    "publico.apps.PublicoConfig",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

# ---------- Middleware ----------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Sprint 2 — isolamento multi-tenant (após AuthMiddleware).
    "core.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

# ---------- Database ----------
# Conexão via DATABASE_URL (PRD §13.6 — credenciais fora do repo).
# environs 14+ não registra mais env.db(); usamos dj_database_url diretamente.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", default="postgres://focusbarber:focusbarber@localhost:5432/focusbarber"),
    ),
}

# ---------- Auth ----------
# Custom User com login por e-mail + role (PRD §8: operações dependem de role).
AUTH_USER_MODEL = "base.User"

# Sprint 3 — login por e-mail explícito (backend custom).
AUTHENTICATION_BACKENDS = [
    "base.backends.EmailBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/perfil/"

# ---------- I18N ----------
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ---------- Static / Media (PRD §13.5) ----------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.StaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------- Security defaults (reforçados em prod) ----------
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"