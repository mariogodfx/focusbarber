"""URLs do projeto FocusBarber.

Rotas base (Sprint 1):
  - /admin/  -> admin Django (Auth base)
  - /health/ -> health check (PRD §13.4.5: Django -> /health/)
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("base.urls")),  # /health/, /login/, /logout/, /perfil/
]