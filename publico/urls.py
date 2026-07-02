"""URLs do app publico - Pagina Publica da barbearia.

Rotas:
  - /<slug>/                    -> pagina publica da barbearia (Sprint 4)
  - /<slug>/agendar/            -> formulario de agendamento (Sprint 6)
  - /<slug>/agendar/sucesso/     -> confirmacao de agendamento (Sprint 6)
"""
from django.urls import path

from .views import AgendamentoSucessoView, AgendamentoView, BarbeariaPublicaView

app_name = "publico"

urlpatterns = [
    path("<slug:slug>/agendar/sucesso/", AgendamentoSucessoView.as_view(), name="agendar_sucesso"),
    path("<slug:slug>/agendar/", AgendamentoView.as_view(), name="agendar"),
    path("<slug:slug>/", BarbeariaPublicaView.as_view(), name="barbearia"),
]
