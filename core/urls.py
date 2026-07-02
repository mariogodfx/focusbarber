"""URLs do app core — Painel do Profissional.

Rotas:
  - /painel/                          → dashboard (convites + barbearias)
  - /painel/convite/<pk>/aceitar/     → aceitar convite (POST)
  - /painel/convite/<pk>/rejeitar/    → rejeitar convite (POST)
  - /painel/convite/<pk>/cancelar/    → cancelar convite (POST)
"""
from django.urls import path

from .views import (
    PainelProfissionalView,
    convite_aceitar,
    convite_cancelar,
    convite_rejeitar,
)

app_name = "core"

urlpatterns = [
    path("painel/", PainelProfissionalView.as_view(), name="painel"),
    path("painel/convite/<int:pk>/aceitar/", convite_aceitar, name="convite_aceitar"),
    path("painel/convite/<int:pk>/rejeitar/", convite_rejeitar, name="convite_rejeitar"),
    path("painel/convite/<int:pk>/cancelar/", convite_cancelar, name="convite_cancelar"),
]
