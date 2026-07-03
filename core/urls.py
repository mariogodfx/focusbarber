"""URLs do app core — Painel do Profissional.

Rotas:
  - /painel/                          → dashboard (convites + barbearias)
  - /painel/convite/<pk>/aceitar/     → aceitar convite (POST)
  - /painel/convite/<pk>/rejeitar/    → rejeitar convite (POST)
  - /painel/convite/<pk>/cancelar/    → cancelar convite (POST)
"""
from django.urls import path

from django.urls import path

from .views import (
    PainelProfissionalView,
    appointment_cancelar,
    appointment_concluir,
    appointment_confirmar,
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
    path("painel/agendamento/<int:pk>/confirmar/", appointment_confirmar, name="appointment_confirmar"),
    path("painel/agendamento/<int:pk>/cancelar/", appointment_cancelar, name="appointment_cancelar"),
    path("painel/agendamento/<int:pk>/concluir/", appointment_concluir, name="appointment_concluir"),
]
