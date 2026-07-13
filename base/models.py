"""
User custom — PRD §8: "Toda operação depende de tenant_id + role".

Login por e-mail (prepara Sprint 3: "login email funcionando") + campo `role`
com os perfis do produto. `tenant` (FK) será adicionado no Sprint 2 (Multi-Tenant).
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinLengthValidator, MaxLengthValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Manager de User com login por e-mail (dispensa username)."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.SUPERADMIN)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser precisa de is_staff=True")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser precisa de is_superuser=True")
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        SUPERADMIN = "superadmin", _("Superadmin SaaS")
        OWNER = "owner", _("Dono da Barbearia")
        MANAGER = "manager", _("Gerente")
        PROFESSIONAL = "professional", _("Profissional")
        CLIENT = "client", _("Cliente")

    # E-mail como identificador de login.
    username = None
    email = models.EmailField(_("e-mail"), unique=True)
    cpf = models.CharField(_("CPF"), max_length=11, unique=True, null=True, blank=True, validators=[MinLengthValidator(11), MaxLengthValidator(11)])
    phone = models.CharField(_("telefone"), max_length=20, blank=True)
    role = models.CharField(
        _("perfil"),
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT,
    )

    # Sprint 2 — multi-tenant: usuário pertence a um tenant (barbearia).
    # Superadmin SaaS (role=superadmin) pode ter tenant=null (escopo global).
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="users",
        verbose_name=_("barbearia"),
        null=True,
        blank=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def is_superadmin(self):
        return self.role == self.Role.SUPERADMIN or self.is_superuser

    class Meta:
        verbose_name = _("usuário")
        verbose_name_plural = _("usuários")

    def __str__(self):
        return self.email