"""Configurações de produção (Docker Swarm). Scaffold — detalhado em sprints de deploy.

Cumpre PRD:
  - §13.4.3 deploy zero-downtime (start-first/rollback) — configurado no compose
  - §13.5 collectstatic --clear — entrypoint
  - §13.6 segredos via Docker Secrets / .env
"""
from .base import *  # noqa: F401,F403

DEBUG = False

#Produção: STATIC_ROOT já vem de base; em prod usamos ManifestStorage.
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])