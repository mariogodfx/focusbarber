"""Views de autenticação — login por e-mail (Sprint 3).

Usa as classes do Django com um formulário custom (campo `email` em vez de
`username`) para entregar uma página de login própria, fora do admin.
"""
import django
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse


def health(request):
    """Endpoint de health check (PRD §13.4.5)."""
    return JsonResponse(
        {"status": "ok", "service": "focusbarber", "django": django.get_version()}
    )


class EmailAuthenticationForm(AuthenticationForm):
    """Form de login identificado por e-mail (label/field em pt-br)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "E-mail"
        self.fields["username"].widget.attrs.update(
            {"autofocus": True, "placeholder": "voce@email.com"}
        )
        self.fields["password"].label = "Senha"


class LoginView(auth_views.LoginView):
    template_name = "base/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    next_page = "base:login"