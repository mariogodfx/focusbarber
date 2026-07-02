"""URLs do app publico — Página Pública da barbearia (Sprint 4).

Rota: /<slug>/  -> exibe a barbearia + serviços ativos (público).
"""
from django.urls import path

from .views import BarbeariaPublicaView

app_name = "publico"

urlpatterns = [
    path("<slug:slug>/", BarbeariaPublicaView.as_view(), name="barbearia"),
]