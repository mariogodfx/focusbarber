"""URLs do projeto FocusBarber.

Rotas base (Sprint 1):
  - /admin/  -> admin Django (Auth base)
  - /health/ -> health check (PRD §13.4.5: Django -> /health/)
Rotas públicas (Sprint 4):
  - /<slug>/ -> página pública da barbearia (app publico)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("base.urls")),  # /health/, /login/, /logout/, /perfil/
    path("", include("core.urls")),  # /painel/ (painel do profissional)
    path("", include("publico.urls")),  # /<slug>/ (página pública)
]

# Media: em DEBUG o Django serve via MEDIA_URL (dev). Em produção a mídia é
# servida via camada controlada (view/proxy) conforme PRD §13.3.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)