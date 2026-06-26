from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.generic import TemplateView

from .views import LoginView, LogoutView, health

app_name = "base"

urlpatterns = [
    path("health/", health, name="health"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path(
        "perfil/",
        login_required(TemplateView.as_view(template_name="base/profile.html")),
        name="profile",
    ),
]