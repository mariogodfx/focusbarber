from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import User


# Perfis que exigem barbearia (tenant) obrigatório no cadastro.
_TENANT_REQUIRED_ROLES = (User.Role.OWNER, User.Role.MANAGER, User.Role.PROFESSIONAL)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Admin do usuário custom (login por e-mail + role) — isolado por tenant.

    Regras (PRD §13.2 / §16):
      - Superadmin SaaS vê TODOS os usuários (acesso global).
      - Demais usuários vêem APENAS os do próprio tenant.
      - Ao criar, o tenant é limitado/forçado ao do usuário logado (não-superadmin).
    """
    ordering = ("email",)
    list_display = ("email", "role", "cpf", "tenant", "is_staff", "is_superuser", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("email", "cpf", "phone")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Dados pessoais"),
            {"fields": ("first_name", "last_name", "cpf", "phone", "role", "tenant")},
        ),
        (
            _("Permissões"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Datas importantes"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "cpf", "role", "tenant", "password1", "password2"),
            },
        ),
    )

    # ---------- Isolamento multi-tenant ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superadmin:
            return qs  # superadmin SaaS vê todos os usuários de todas as barbearias
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return qs.none()
        return qs.filter(tenant=tenant)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Validação: role owner/manager/professional exige tenant preenchido.
        # Injeta um clean no form que levanta ValidationError em `tenant`.
        original_clean = form.clean

        def _clean(form_self):
            cleaned = original_clean(form_self)
            role = cleaned.get("role")
            tenant = cleaned.get("tenant")
            if role in _TENANT_REQUIRED_ROLES and not tenant:
                raise ValidationError(
                    {"tenant": _("Informe a barbearia para este perfil.")}
                )
            return cleaned

        form.clean = _clean
        if not request.user.is_superadmin:
            # Não-superadmin só pode criar/editar usuários do próprio tenant.
            tenant = getattr(request, "tenant", None)
            if tenant is not None and "tenant" in form.base_fields:
                field = form.base_fields["tenant"]
                field.queryset = field.queryset.filter(pk=tenant.pk)
                if obj is None:
                    field.initial = tenant
            # Não-superadmin NÃO pode selecionar o perfil superadmin SaaS.
            if "role" in form.base_fields:
                role_field = form.base_fields["role"]
                role_field.choices = [
                    (value, label)
                    for value, label in User.Role.choices
                    if value != User.Role.SUPERADMIN
                ]
                if obj is None:
                    role_field.initial = User.Role.CLIENT
        return form

    def save_model(self, request, obj, form, change):
        # Garante que não-superadmin não crie usuário em tenant alheio.
        if not request.user.is_superadmin and obj.tenant_id is None:
            obj.tenant = getattr(request, "tenant", None)
        # Defesa em profundidade: não-superadmin jamais atribui role=superadmin.
        if not request.user.is_superadmin:
            obj.role = form.cleaned_data.get("role", obj.role)
            if obj.role == User.Role.SUPERADMIN:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied(
                    "Apenas superadmin SaaS pode criar usuários superadmin."
                )
        super().save_model(request, obj, form, change)