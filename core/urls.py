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
    appointment_cancelar,
    appointment_concluir,
    appointment_confirmar,
    convite_aceitar,
    convite_cancelar,
    convite_rejeitar,
    produto_criar,
    produto_inativar,
    sessao_adicionar_produto,
    sessao_cancelar,
    sessao_fechar,
    sessao_iniciar,
    sessao_iniciar_avulso,
    sessao_remover_produto,
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
    path("painel/sessao/<int:pk>/iniciar/", sessao_iniciar, name="sessao_iniciar"),
    path("painel/sessao/iniciar-avulso/", sessao_iniciar_avulso, name="sessao_iniciar_avulso"),
    path("painel/sessao/<int:pk>/adicionar-produto/", sessao_adicionar_produto, name="sessao_adicionar_produto"),
    path("painel/sessao/<int:pk>/fechar/", sessao_fechar, name="sessao_fechar"),
    path("painel/sessao/<int:pk>/cancelar/", sessao_cancelar, name="sessao_cancelar"),
    path("painel/item-sessao/<int:pk>/remover/", sessao_remover_produto, name="sessao_remover_produto"),
    path("painel/produto/criar/", produto_criar, name="produto_criar"),
    path("painel/produto/<int:pk>/inativar/", produto_inativar, name="produto_inativar"),
]
