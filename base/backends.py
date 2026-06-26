"""
Backend de autenticação por e-mail — PRD Sprint 3: "login email funcionando".

O Django já autentica por USERNAME_FIELD (que é 'email'); este backend torna o
comportamento explícito e adiciona checagens de segurança (is_active).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailBackend(ModelBackend):
    """Autentica pelo campo `email` (case-insensitive) + senha."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = username or kwargs.get("email")
        if not email or not password:
            return None
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(email__iexact=email)
        except UserModel.DoesNotExist:
            # Roda a verificação de senha padrão para não vazar timing info.
            UserModel().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        # is_active obrigatório — proíbe login de usuários inativos.
        return getattr(user, "is_active", True)